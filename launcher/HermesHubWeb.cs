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

            // 2. Check if server is already running and healthy
            bool serverWasAlreadyRunning = IsServerHealthy(healthUrl);
            Process serverProcess = null;

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
                        string why = "";
                        try { why = serverProcess.StandardError.ReadToEnd(); } catch { }
                        if (string.IsNullOrEmpty(why))
                        {
                            try { why = serverProcess.StandardOutput.ReadToEnd(); } catch { }
                        }
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
                browserPsi.Arguments = string.Format("--app=\"{0}\" --window-size=1400,900", targetUrl);
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

            // 5. Server Lifecycle:
            // If the server was started by this launcher session and browser is tracked,
            // wait for browser window to close, then gracefully terminate server process.
            if (!serverWasAlreadyRunning && serverProcess != null && !serverProcess.HasExited && browserProc != null)
            {
                try
                {
                    browserProc.WaitForExit();
                }
                catch { }

                try
                {
                    if (!serverProcess.HasExited)
                    {
                        serverProcess.Kill();
                    }
                }
                catch { }
            }
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
