using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

namespace HermesHub
{
    public static class WebLauncher
    {
        private static Mutex instanceMutex;

        [STAThread]
        public static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string hermesHome = Environment.GetEnvironmentVariable("HERMES_HOME");
            if (string.IsNullOrEmpty(hermesHome))
            {
                hermesHome = Path.Combine(localAppData, "hermes");
            }

            // 1. Determine Web API Host and Port from hub_settings.json or default
            string host = "127.0.0.1";
            int port = 5800;
            string settingsFile = Path.Combine(hermesHome, "hub_settings.json");
            if (File.Exists(settingsFile))
            {
                try
                {
                    string json = File.ReadAllText(settingsFile, Encoding.UTF8);
                    int pIdx = json.IndexOf("\"web_api_port\":", StringComparison.OrdinalIgnoreCase);
                    if (pIdx >= 0)
                    {
                        int colon = json.IndexOf(':', pIdx);
                        int comma = json.IndexOfAny(new char[] { ',', '}', '\r', '\n' }, colon + 1);
                        if (colon >= 0 && comma > colon)
                        {
                            string pStr = json.Substring(colon + 1, comma - colon - 1).Trim();
                            int parsedPort;
                            if (int.TryParse(pStr, out parsedPort) && parsedPort > 0 && parsedPort < 65536)
                            {
                                port = parsedPort;
                            }
                        }
                    }
                    int hIdx = json.IndexOf("\"web_api_host\":", StringComparison.OrdinalIgnoreCase);
                    if (hIdx >= 0)
                    {
                        int q1 = json.IndexOf('"', hIdx + 15);
                        int q2 = json.IndexOf('"', q1 + 1);
                        if (q1 >= 0 && q2 > q1)
                        {
                            string hStr = json.Substring(q1 + 1, q2 - q1 - 1).Trim();
                            if (!string.IsNullOrEmpty(hStr) && hStr != "0.0.0.0")
                            {
                                host = hStr;
                            }
                        }
                    }
                }
                catch { }
            }

            string targetUrl = string.Format("http://{0}:{1}/", host, port);
            string healthUrl = string.Format("http://{0}:{1}/api/health", host, port);

            bool firstInstance;
            instanceMutex = new Mutex(true, "Local\\HermesHubWeb", out firstInstance);
            if (!firstInstance) { Process.Start(targetUrl); return; }
            // Adopt no unknown server: stop only a verified process from our installation.
            try { StopOwnedRuntime(hermesHome, false); }
            catch (Exception ex) { MessageBox.Show(ex.Message, "Hermes Hub", MessageBoxButtons.OK, MessageBoxIcon.Error); return; }

            // 2. Check if server is already running and healthy
            bool serverWasAlreadyRunning = IsServerHealthy(healthUrl);
            Process serverProcess = null;
            StringBuilder serverLog = new StringBuilder();

            if (!serverWasAlreadyRunning)
            {
                // Find Python
                string hermesPythonW = Path.Combine(hermesHome, @"hermes-agent\venv\Scripts\pythonw.exe");
                string hermesPython = Path.Combine(hermesHome, @"hermes-agent\venv\Scripts\python.exe");
                string exe = File.Exists(hermesPythonW) ? hermesPythonW : hermesPython;

                if (!File.Exists(exe))
                {
                    MessageBox.Show(
                        "Hermes Python not found:\n" + exe + "\n\nPlease install Hermes Agent first.",
                        "Hermes Hub", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }

                string pluginSrc = Path.Combine(hermesHome, @"plugins\antigravity-provider\src");
                string agentDir = Path.Combine(hermesHome, "hermes-agent");
                string baseDir = AppDomain.CurrentDomain.BaseDirectory;
                string hubSrc = Path.GetFullPath(Path.Combine(baseDir, @"..\src"));

                StringBuilder script = new StringBuilder();
                script.AppendLine("import sys");
                if (Directory.Exists(pluginSrc))
                    script.AppendLine("sys.path.insert(0, r'" + pluginSrc.Replace('\\', '/') + "')");
                if (Directory.Exists(agentDir))
                    script.AppendLine("sys.path.insert(0, r'" + agentDir.Replace('\\', '/') + "')");
                if (Directory.Exists(hubSrc))
                    script.AppendLine("sys.path.insert(0, r'" + hubSrc.Replace('\\', '/') + "')");
                script.AppendLine("from antigravity_provider.router.web.server import run_server");
                script.AppendLine("run_server()");

                string entryScript = Path.Combine(hermesHome, "hermes_hub_web_entry.py");
                try
                {
                    File.WriteAllText(entryScript, script.ToString(), Encoding.UTF8);
                }
                catch (Exception ex)
                {
                    MessageBox.Show("Cannot write entry script:\n" + ex.Message, "Hermes Hub", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }

                ProcessStartInfo serverPsi = new ProcessStartInfo();
                serverPsi.FileName = exe;
                serverPsi.Arguments = "\"" + entryScript + "\"";
                serverPsi.WorkingDirectory = hermesHome;
                serverPsi.UseShellExecute = false;
                serverPsi.CreateNoWindow = true;
                serverPsi.WindowStyle = ProcessWindowStyle.Hidden;
                // Вывод перехватываем, чтобы при падении показать причину, а не
                // голое «terminated unexpectedly». Без этого владелец видит факт
                // отказа и ни слова о том, чего не хватает.
                serverPsi.RedirectStandardError = true;
                serverPsi.RedirectStandardOutput = true;

                try
                {
                    serverProcess = Process.Start(serverPsi);
                    DataReceivedEventHandler collect = delegate(object sender, DataReceivedEventArgs item) {
                        if (item.Data == null) return;
                        lock (serverLog) { serverLog.AppendLine(item.Data); if (serverLog.Length > 4000) serverLog.Remove(0, serverLog.Length - 4000); }
                    };
                    serverProcess.ErrorDataReceived += collect;
                    serverProcess.OutputDataReceived += collect;
                    serverProcess.BeginErrorReadLine();
                    serverProcess.BeginOutputReadLine();
                }
                catch (Exception ex)
                {
                    MessageBox.Show("Failed to start Hermes Hub web server:\n" + ex.Message, "Hermes Hub", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }

                // 3. Poll /api/health with timeout (up to 15s)
                bool ready = false;
                for (int i = 0; i < 75; i++)
                {
                    if (IsServerHealthy(healthUrl))
                    {
                        ready = true;
                        break;
                    }
                    if (serverProcess.HasExited)
                    {
                        string why;
                        lock (serverLog) { why = serverLog.ToString(); }
                        if (why.Length > 1500) why = why.Substring(why.Length - 1500);
                        string msg = "Веб-сервер Hermes Hub завершился с ошибкой.";
                        if (!string.IsNullOrEmpty(why)) msg += Environment.NewLine + Environment.NewLine + why.Trim();
                        MessageBox.Show(msg, "Hermes Hub", MessageBoxButtons.OK, MessageBoxIcon.Error);
                        return;
                    }
                    Thread.Sleep(200);
                }

                if (!ready)
                {
                    MessageBox.Show("Hermes Hub web server failed to respond within 15 seconds.", "Hermes Hub", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    if (serverProcess != null && !serverProcess.HasExited)
                    {
                        try { serverProcess.Kill(); } catch { }
                    }
                    return;
                }
            }

            // 4. Locate browser in strict priority: Edge -> Chrome -> Chromium registry -> Fallback
            string browserPath = FindChromiumBrowser();
            Process browserProc = null;


            if (!string.IsNullOrEmpty(browserPath))
            {
                ProcessStartInfo browserPsi = new ProcessStartInfo();
                browserPsi.FileName = browserPath;
                // Отдельный профиль браузера обязателен. Без него запущенный
                // msedge.exe передаёт задачу УЖЕ РАБОТАЮЩЕМУ экземпляру и тут же
                // завершается: WaitForExit возвращается мгновенно, лаунчер
                // считает окно закрытым и убивает сервер, пока страница ещё
                // грузится. Владелец видел ERR_CONNECTION_REFUSED.
                string browserProfile = Path.Combine(hermesHome, "web_browser_profile");
                try { Directory.CreateDirectory(browserProfile); } catch { }
                browserPsi.Arguments = string.Format(
                    "--app=\"{0}\" --window-size=1400,900 --user-data-dir=\"{1}\" --no-first-run --no-default-browser-check",
                    targetUrl, browserProfile);
                browserPsi.UseShellExecute = false;

                try
                {
                    browserProc = Process.Start(browserPsi);

                }
                catch (Exception ex)
                {
                    MessageBox.Show(
                        "Не удалось запустить браузер в режиме приложения:\n" + ex.Message + "\n\nОткрываю стандартный браузер.",
                        "Hermes Hub", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    Process.Start(targetUrl);
                }
            }
            else
            {
                // No Chromium browser found
                MessageBox.Show(
                    "Браузер с поддержкой режима приложения (Microsoft Edge или Google Chrome) не найден.\n\n" +
                    "Интерфейс будет открыт в стандартном браузере с адресной строкой.",
                    "Hermes Hub", MessageBoxButtons.OK, MessageBoxIcon.Information);
                try
                {
                    Process.Start(targetUrl);
                }
                catch (Exception ex)
                {
                    MessageBox.Show("Не удалось открыть браузер: " + ex.Message, "Hermes Hub", MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
            }

            Application.Run(new HubContext(hermesHome, targetUrl, browserPath, browserProc));
            instanceMutex.ReleaseMutex();
        }

        // Restrict cleanup to this installation. Never kill arbitrary Python/browser processes.
        public static void StopOwnedRuntime(string home, bool includeLauncher)
        {
            string escaped = Path.GetFullPath(home).TrimEnd('\\').Replace("'", "''");
            string script = "$ErrorActionPreference='Stop'; $root='" + escaped + "'; " +
                "$py=@((Join-Path $root 'hermes-agent\\venv\\Scripts\\python.exe'),(Join-Path $root 'hermes-agent\\venv\\Scripts\\pythonw.exe')); " +
                "$all=@(Get-CimInstance Win32_Process); $protected=@($PID); $cursor=$PID; " +
                "while ($cursor) { $node=$all | Where-Object ProcessId -eq $cursor | Select-Object -First 1; if (!$node) { break }; $cursor=$node.ParentProcessId; if ($cursor -in $protected) { break }; $protected+= $cursor }; " +
                "function Stop-HubBranch([int]$processId) { foreach ($child in @($all | Where-Object ParentProcessId -eq $processId)) { if ($child.ProcessId -notin $protected) { Stop-HubBranch $child.ProcessId } }; " +
                "if (Get-Process -Id $processId -ErrorAction SilentlyContinue) { Stop-Process -Id $processId -Force -ErrorAction Stop } }; " +
                "$targets=@($all | Where-Object { " +
                "($_.ExecutablePath -in $py -and ($_.CommandLine -match 'hermes_hub_web_entry\\.py|antigravity_provider\\.router\\.web'))" +
                " -or ($_.Name -in @('msedge.exe','chrome.exe','chromium.exe') -and $_.CommandLine -match ('--user-data-dir=[\\x22]?'+[regex]::Escape((Join-Path $root 'web_browser_profile'))+'[\\x22]?(?:\\s|$)'))" +
                (includeLauncher ? " -or ($_.Name -eq 'HermesHubWeb.exe' -and ($_.ExecutablePath -eq (Join-Path $root 'HermesHubWeb.exe') -or $_.ExecutablePath -eq (Join-Path $env:LOCALAPPDATA 'Programs\\HermesHub\\HermesHubWeb.exe')))" : "") +
                " }); foreach ($target in $targets) { Stop-HubBranch $target.ProcessId; " +
                "if (Get-Process -Id $target.ProcessId -ErrorAction SilentlyContinue) { throw 'Не удалось остановить прежний процесс Hermes Hub' } }";
            ProcessStartInfo info = new ProcessStartInfo("powershell.exe", "-NoProfile -NonInteractive -EncodedCommand " + Convert.ToBase64String(Encoding.Unicode.GetBytes(script)));
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.WindowStyle = ProcessWindowStyle.Hidden;
            using (Process process = Process.Start(info))
            {
                if (!process.WaitForExit(20000)) { process.Kill(); throw new IOException("Остановка прежнего сервера превысила 20 секунд"); }
                if (process.ExitCode != 0) throw new IOException("Не удалось остановить прежний сервер. Обновление отменено.");
            }
        }

        private sealed class HubContext : ApplicationContext
        {
            private readonly NotifyIcon tray;
            private readonly System.Windows.Forms.Timer timer;
            private readonly string home, url, browserPath;
            private Process browser;
            private bool watching, hadWindow, closing;

            public HubContext(string homePath, string targetUrl, string browserExe, Process browserProcess)
            {
                home = homePath; url = targetUrl; browserPath = browserExe; browser = browserProcess;
                watching = browser != null;
                tray = new NotifyIcon();
                tray.Icon = System.Drawing.SystemIcons.Application;
                tray.Text = "Hermes Hub — работает в фоне";
                ContextMenuStrip menu = new ContextMenuStrip();
                menu.Items.Add("Открыть", null, delegate { Open(); });
                menu.Items.Add("Выход", null, delegate { ExitCompletely(); });
                tray.ContextMenuStrip = menu;
                tray.DoubleClick += delegate { Open(); };
                tray.Visible = true;
                timer = new System.Windows.Forms.Timer(); timer.Interval = 500;
                timer.Tick += delegate { WatchWindow(); }; timer.Start();
            }

            private void WatchWindow()
            {
                if (!watching || closing || browser == null) return;
                bool closed;
                try {
                    browser.Refresh();
                    if (!browser.HasExited && browser.MainWindowHandle != IntPtr.Zero) hadWindow = true;
                    closed = browser.HasExited || (hadWindow && browser.MainWindowHandle == IntPtr.Zero);
                } catch { closed = true; }
                if (!closed) return;
                watching = false;
                DialogResult answer = MessageBox.Show("Закрыть Hermes Hub полностью?\n\nДа — остановить сервер и фоновые опросы.\nНет — оставить в фоне (значок в области уведомлений).", "Hermes Hub", MessageBoxButtons.YesNo, MessageBoxIcon.Question);
                if (answer == DialogResult.Yes) ExitCompletely();
            }

            private void Open()
            {
                if (closing) return;
                try {
                    if (browser != null && !browser.HasExited && browser.MainWindowHandle != IntPtr.Zero) {
                        ShowWindow(browser.MainWindowHandle, 9); SetForegroundWindow(browser.MainWindowHandle); return;
                    }
                    if (string.IsNullOrEmpty(browserPath)) { Process.Start(url); return; }
                    ProcessStartInfo info = new ProcessStartInfo(browserPath,
                        "--app=\"" + url + "\" --window-size=1400,900 --user-data-dir=\"" + Path.Combine(home, "web_browser_profile") + "\" --no-first-run --no-default-browser-check");
                    info.UseShellExecute = false;
                    browser = Process.Start(info); watching = true; hadWindow = false;
                } catch (Exception ex) { MessageBox.Show(ex.Message, "Hermes Hub"); }
            }

            private void ExitCompletely()
            {
                if (closing) return;
                closing = true; timer.Stop();
                try {
                    if (browser != null && !browser.HasExited) {
                        ProcessStartInfo kill = new ProcessStartInfo("taskkill.exe", "/PID " + browser.Id + " /T /F");
                        kill.UseShellExecute = false; kill.CreateNoWindow = true;
                        using (Process process = Process.Start(kill)) { process.WaitForExit(5000); }
                    }
                    // Неудачная остановка не повод отменять выход: владелец нажал
                    // «закрыть», и программа обязана закрыться. Прежде окно с
                    // ошибкой возвращало его обратно в работающее приложение.
                    try { StopOwnedRuntime(home, false); }
                    catch (Exception stopEx) {
                        MessageBox.Show("Часть процессов остановить не удалось: " + stopEx.Message + " Hermes Hub закроется; при необходимости снимите их в диспетчере задач.", "Hermes Hub", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    }
                    tray.Visible = false; tray.Dispose(); timer.Dispose(); ExitThread();
                } catch (Exception ex) {
                    closing = false; timer.Start();
                    MessageBox.Show("Не удалось завершить всё: " + ex.Message, "Hermes Hub", MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
            }
            [System.Runtime.InteropServices.DllImport("user32.dll")] private static extern bool SetForegroundWindow(IntPtr handle);
            [System.Runtime.InteropServices.DllImport("user32.dll")] private static extern bool ShowWindow(IntPtr handle, int command);
        }

        public static bool IsServerHealthy(string url)
        {
            try
            {
                HttpWebRequest req = (HttpWebRequest)WebRequest.Create(url);
                req.Timeout = 800;
                req.Method = "GET";
                using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
                {
                    if (resp.StatusCode == HttpStatusCode.OK)
                    {
                        using (StreamReader r = new StreamReader(resp.GetResponseStream(), Encoding.UTF8))
                        {
                            string txt = r.ReadToEnd();
                            return txt.Contains("\"ok\":true") || txt.Contains("\"ok\": true");
                        }
                    }
                }
            }
            catch { }
            return false;
        }

        public static string FindChromiumBrowser()
        {
            // 1. Microsoft Edge
            string[] edgePaths = new string[]
            {
                @"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                @"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), @"Microsoft\Edge\Application\msedge.exe")
            };
            foreach (string p in edgePaths)
            {
                if (File.Exists(p)) return p;
            }

            string edgeReg = GetAppPathFromRegistry("msedge.exe");
            if (!string.IsNullOrEmpty(edgeReg) && File.Exists(edgeReg)) return edgeReg;

            // 2. Google Chrome
            string[] chromePaths = new string[]
            {
                @"C:\Program Files\Google\Chrome\Application\chrome.exe",
                @"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), @"Google\Chrome\Application\chrome.exe")
            };
            foreach (string p in chromePaths)
            {
                if (File.Exists(p)) return p;
            }

            string chromeReg = GetAppPathFromRegistry("chrome.exe");
            if (!string.IsNullOrEmpty(chromeReg) && File.Exists(chromeReg)) return chromeReg;

            // 3. Brave / Vivaldi / Chromium
            string[] otherPaths = new string[]
            {
                @"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), @"BraveSoftware\Brave-Browser\Application\brave.exe"),
                @"C:\Program Files\Vivaldi\Application\vivaldi.exe",
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), @"Vivaldi\Application\vivaldi.exe")
            };
            foreach (string p in otherPaths)
            {
                if (File.Exists(p)) return p;
            }

            string braveReg = GetAppPathFromRegistry("brave.exe");
            if (!string.IsNullOrEmpty(braveReg) && File.Exists(braveReg)) return braveReg;

            return null;
        }

        private static string GetAppPathFromRegistry(string exeName)
        {
            try
            {
                string key = @"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\" + exeName;
                using (RegistryKey rk = Registry.LocalMachine.OpenSubKey(key))
                {
                    if (rk != null)
                    {
                        object val = rk.GetValue(null);
                        if (val != null) return val.ToString();
                    }
                }
                using (RegistryKey rk = Registry.CurrentUser.OpenSubKey(key))
                {
                    if (rk != null)
                    {
                        object val = rk.GetValue(null);
                        if (val != null) return val.ToString();
                    }
                }
            }
            catch { }
            return null;
        }
    }
}
