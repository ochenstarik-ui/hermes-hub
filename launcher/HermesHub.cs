using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace HermesHub
{
    static class Program
    {
        private static Process serverProcess = null;
        private static string logFilePath = "";
        private static bool isDebug = false;
        private static readonly object _logLock = new object();
        private static StringBuilder serverStdErr = new StringBuilder();
        private static StringBuilder serverStdOut = new StringBuilder();

        [STAThread]
        static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            foreach (string arg in args)
            {
                if (arg.Equals("--debug", StringComparison.OrdinalIgnoreCase) || arg.Equals("-d", StringComparison.OrdinalIgnoreCase))
                {
                    isDebug = true;
                }
            }

            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string hermesHome = Path.Combine(localAppData, "hermes");

            // Ensure %LOCALAPPDATA%\hermes\logs exists
            string logsDir = Path.Combine(hermesHome, "logs");
            try
            {
                if (!Directory.Exists(logsDir))
                {
                    Directory.CreateDirectory(logsDir);
                }
            }
            catch { }

            logFilePath = Path.Combine(logsDir, "hermes-hub.log");

            Log("================================================================================");
            Log(string.Format("Hermes Hub Launcher Started at {0}", DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss")));
            Log("================================================================================");
            if (isDebug) Log("[Debug Mode Active]");

            int port = 8765;
            string url = string.Format("http://127.0.0.1:{0}", port);
            string healthUrl = url + "/api/status";

            // 1. Check if Hermes Hub is already running healthy on default port (instant launch!)
            if (IsEndpointHealthy(healthUrl, 1000))
            {
                Log(string.Format("Hermes Hub backend already running and healthy at {0}. Launching UI directly...", url));
                LaunchBrowser(url);
                return;
            }

            // 2. Resolve Hermes Python Executable dynamically
            string hermesPython = Path.Combine(hermesHome, @"hermes-agent\venv\Scripts\python.exe");
            if (!File.Exists(hermesPython))
            {
                string altPython = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, @"venv\Scripts\python.exe");
                if (File.Exists(altPython)) hermesPython = altPython;
            }

            if (!File.Exists(hermesPython))
            {
                string errMsg = string.Format("Hermes Python environment not found at:\n{0}\n\nPlease ensure Hermes is installed.", hermesPython);
                Log("[FATAL] " + errMsg);
                MessageBox.Show(errMsg, "Hermes Hub Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }

            Log("Hermes Python executable: " + hermesPython);

            // 3. Discover Plugin Search Paths Dynamically
            StringBuilder pathsCode = new StringBuilder();
            string localAgPlugin = Path.Combine(hermesHome, @"plugins\antigravity-provider\src");
            if (Directory.Exists(localAgPlugin))
            {
                pathsCode.Append(string.Format("r'{0}', ", localAgPlugin.Replace('\\', '/')));
            }

            string baseDirPlugin = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, @"plugins\antigravity-provider\src");
            if (Directory.Exists(baseDirPlugin) && !baseDirPlugin.Equals(localAgPlugin, StringComparison.OrdinalIgnoreCase))
            {
                pathsCode.Append(string.Format("r'{0}', ", baseDirPlugin.Replace('\\', '/')));
            }

            string hermesAgentDir = Path.Combine(hermesHome, "hermes-agent");
            if (Directory.Exists(hermesAgentDir))
            {
                pathsCode.Append(string.Format("r'{0}', ", hermesAgentDir.Replace('\\', '/')));
            }

            string pluginPathsList = pathsCode.ToString().TrimEnd(' ', ',');
            Log("Discovered plugin search paths: " + pluginPathsList);

            // 4. Check if standard port 8765 is blocked by a non-responding process
            if (IsPortListening(port))
            {
                // Port has a socket listening, but it didn't respond to /api/status. Try dynamic port.
                port = FindFreePortSafe();
                url = string.Format("http://127.0.0.1:{0}", port);
                healthUrl = url + "/api/status";
                Log(string.Format("Default port 8765 was occupied by an unready process. Selected port: {0}", port));
            }
            else
            {
                Log(string.Format("Using standard port: {0}", port));
            }

            // 5. Write Clean Bootstrap Script File (hermes_hub_entry.py)
            string launcherScript = Path.Combine(hermesHome, "hermes_hub_entry.py");
            StringBuilder scriptContent = new StringBuilder();
            scriptContent.AppendLine("# Auto-generated launcher bootstrap for Hermes Hub");
            scriptContent.AppendLine("import sys, argparse");
            scriptContent.AppendLine(string.Format("plugin_paths = [{0}]", pluginPathsList));
            scriptContent.AppendLine("for p in plugin_paths:");
            scriptContent.AppendLine("    if p and p not in sys.path:");
            scriptContent.AppendLine("        sys.path.insert(0, p)");
            scriptContent.AppendLine("parser = argparse.ArgumentParser()");
            scriptContent.AppendLine("parser.add_argument('--port', type=int, default=8765)");
            scriptContent.AppendLine("args, _ = parser.parse_known_args()");
            scriptContent.AppendLine("from antigravity_provider.router.cli_commands import main");
            scriptContent.AppendLine("sys.exit(main(['hub', '--port', str(args.port), '--no-browser']))");

            try
            {
                File.WriteAllText(launcherScript, scriptContent.ToString(), Encoding.UTF8);
                Log("Wrote launcher entry script: " + launcherScript);
            }
            catch (Exception ex)
            {
                Log("[WARN] Could not write entry script: " + ex.Message);
            }

            // 6. Start Background Backend Process with Redirected Output
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = hermesPython;
            psi.Arguments = string.Format("\"{0}\" --port {1}", launcherScript, port);
            psi.WorkingDirectory = Directory.Exists(hermesHome) ? hermesHome : AppDomain.CurrentDomain.BaseDirectory;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.WindowStyle = ProcessWindowStyle.Hidden;
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;

            try
            {
                serverProcess = new Process();
                serverProcess.StartInfo = psi;
                serverProcess.OutputDataReceived += (s, e) =>
                {
                    if (!string.IsNullOrEmpty(e.Data))
                    {
                        lock (_logLock) { serverStdOut.AppendLine(e.Data); }
                        Log("[Backend stdout] " + e.Data);
                    }
                };
                serverProcess.ErrorDataReceived += (s, e) =>
                {
                    if (!string.IsNullOrEmpty(e.Data))
                    {
                        lock (_logLock) { serverStdErr.AppendLine(e.Data); }
                        Log("[Backend stderr] " + e.Data);
                    }
                };

                serverProcess.Start();
                serverProcess.BeginOutputReadLine();
                serverProcess.BeginErrorReadLine();

                Log(string.Format("Launched backend process (PID: {0}) on port {1}", serverProcess.Id, port));
            }
            catch (Exception ex)
            {
                string errMsg = "Failed to launch Hermes Hub backend process:\n" + ex.Message;
                Log("[FATAL] " + errMsg);
                MessageBox.Show(errMsg, "Hermes Hub Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
                Cleanup();
                return;
            }

            AppDomain.CurrentDomain.ProcessExit += (s, e) => Cleanup();

            // 7. Health Check Gate: Poll /api/status up to 20 seconds (100 * 200ms)
            bool isReady = false;
            int maxAttempts = 100;
            Log(string.Format("Polling backend health at {0}...", healthUrl));

            for (int attempt = 1; attempt <= maxAttempts; attempt++)
            {
                if (serverProcess.HasExited)
                {
                    Log(string.Format("[FATAL] Backend server process terminated prematurely with exit code {0}", serverProcess.ExitCode));
                    break;
                }

                if (IsEndpointHealthy(healthUrl, 400))
                {
                    isReady = true;
                    Log(string.Format("[PASS] Backend health check OK (HTTP 200) on attempt {0} ({1:F1}s)", attempt, attempt * 0.2));
                    break;
                }

                Thread.Sleep(200);
            }

            // If backend failed to respond or crashed: Fail-closed gate
            if (!isReady)
            {
                string stdErrText;
                lock (_logLock) { stdErrText = serverStdErr.ToString().Trim(); }
                if (string.IsNullOrEmpty(stdErrText))
                {
                    stdErrText = GetRecentLogLines(25);
                }

                string failMsg = string.Format(
                    "Hermes Hub backend failed to start.\n\n" +
                    "Endpoint: {0}\n\n" +
                    "Error / Output:\n{1}\n\n" +
                    "Full log file:\n{2}",
                    url, stdErrText, logFilePath
                );

                Log("[FATAL] Startup health check failed. Aborting UI launch.");
                MessageBox.Show(failMsg, "Hermes Hub Startup Failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
                Cleanup();
                return;
            }

            // 8. Launch UI in Microsoft Edge App Mode or Default Browser
            LaunchBrowser(url);
        }

        private static void LaunchBrowser(string url)
        {
            string edgePath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), @"Microsoft\Edge\Application\msedge.exe");
            if (!File.Exists(edgePath))
            {
                edgePath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), @"Microsoft\Edge\Application\msedge.exe");
            }

            Process browserProc = null;
            if (File.Exists(edgePath))
            {
                Log("Opening Edge in standalone App Mode: " + url);
                ProcessStartInfo edgePsi = new ProcessStartInfo();
                edgePsi.FileName = edgePath;
                edgePsi.Arguments = string.Format("--app=\"{0}\" --window-size=1280,860 --app-id=hermes-hub", url);
                edgePsi.UseShellExecute = false;

                try
                {
                    browserProc = Process.Start(edgePsi);
                }
                catch (Exception ex)
                {
                    Log("[WARN] Failed to open Edge app mode, falling back to default browser: " + ex.Message);
                    Process.Start(url);
                }
            }
            else
            {
                Log("Opening default browser: " + url);
                Process.Start(url);
            }

            if (browserProc != null && serverProcess != null)
            {
                browserProc.WaitForExit();
                Log("UI Window closed by user. Terminating backend...");
                Cleanup();
            }
        }

        private static bool IsEndpointHealthy(string url, int timeoutMs)
        {
            try
            {
                HttpWebRequest req = (HttpWebRequest)WebRequest.Create(url);
                req.Timeout = timeoutMs;
                req.Method = "GET";
                using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
                {
                    return resp.StatusCode == HttpStatusCode.OK;
                }
            }
            catch
            {
                return false;
            }
        }

        private static bool IsPortListening(int port)
        {
            try
            {
                using (TcpClient client = new TcpClient())
                {
                    IAsyncResult ar = client.BeginConnect(IPAddress.Loopback, port, null, null);
                    bool success = ar.AsyncWaitHandle.WaitOne(200);
                    if (success && client.Connected)
                    {
                        client.EndConnect(ar);
                        return true;
                    }
                }
            }
            catch { }
            return false;
        }

        private static int FindFreePortSafe()
        {
            for (int p = 8766; p <= 8790; p++)
            {
                if (!IsPortListening(p))
                {
                    return p;
                }
            }
            return 8766;
        }

        private static void Log(string message)
        {
            lock (_logLock)
            {
                string line = string.Format("[{0}] {1}", DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff"), message);
                if (isDebug)
                {
                    try { Console.WriteLine(line); } catch { }
                }
                try
                {
                    if (!string.IsNullOrEmpty(logFilePath))
                    {
                        File.AppendAllText(logFilePath, line + Environment.NewLine, Encoding.UTF8);
                    }
                }
                catch { }
            }
        }

        private static string GetRecentLogLines(int count)
        {
            try
            {
                if (File.Exists(logFilePath))
                {
                    string[] lines = File.ReadAllLines(logFilePath);
                    int start = Math.Max(0, lines.Length - count);
                    StringBuilder sb = new StringBuilder();
                    for (int i = start; i < lines.Length; i++)
                    {
                        sb.AppendLine(lines[i]);
                    }
                    return sb.ToString().Trim();
                }
            }
            catch { }
            return "(log unavailable)";
        }

        private static void Cleanup()
        {
            Log("Cleaning up launcher and terminating backend processes...");
            if (serverProcess != null && !serverProcess.HasExited)
            {
                try
                {
                    serverProcess.Kill();
                    serverProcess.WaitForExit(2000);
                    Log(string.Format("Backend process (PID: {0}) terminated.", serverProcess.Id));
                }
                catch (Exception ex)
                {
                    Log("Error terminating backend process: " + ex.Message);
                }
            }
        }
    }
}
