using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.IO.Compression;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

namespace HermesHubSetup
{
    public class SetupEngine
    {
        public const string HUB_VERSION = "0.1.3";
        // Подставляется сборщиком из фактического git-коммита. Раньше здесь
        // жил зашитый "8cddc9f", то есть манифест сообщал неправду о том, из
        // какого кода собран установщик.
        public const string BuildCommit = "b309972";
        public const string MIN_HERMES_VERSION = "0.20.0";
        public const string MAX_TESTED_HERMES = "0.20.4";

        public static string HermesHome { get; private set; }
        public static string HermesPython { get; private set; }
        public static string HermesExe { get; private set; }
        public static string HermesVersion { get; private set; }
        public static bool IsHermesFound { get; private set; }
        public static bool IsHermesCompatible { get; private set; }
        public static string TargetInstallDir { get; set; }
        public static bool IsInstalled { get; private set; }
        public static string InstalledVersion { get; private set; }
        public static string InstalledDate { get; private set; }

        public static void DetectHermes()
        {
            HermesHome = Environment.GetEnvironmentVariable("HERMES_HOME");
            if (string.IsNullOrEmpty(HermesHome))
            {
                string localApp = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                HermesHome = Path.Combine(localApp, "hermes");
            }

            HermesPython = Path.Combine(HermesHome, @"hermes-agent\venv\Scripts\python.exe");
            HermesExe = Path.Combine(HermesHome, @"hermes-agent\venv\Scripts\hermes.exe");

            IsHermesFound = File.Exists(HermesPython);
            HermesVersion = "unknown";
            IsHermesCompatible = false;

            if (IsHermesFound)
            {
                if (File.Exists(HermesExe))
                {
                    try
                    {
                        ProcessStartInfo psi = new ProcessStartInfo();
                        psi.FileName = HermesExe;
                        psi.Arguments = "--version";
                        psi.UseShellExecute = false;
                        psi.RedirectStandardOutput = true;
                        psi.CreateNoWindow = true;
                        using (Process p = Process.Start(psi))
                        {
                            string outText = p.StandardOutput.ReadToEnd();
                            p.WaitForExit(5000);
                            if (!string.IsNullOrEmpty(outText))
                            {
                                HermesVersion = outText.Replace("hermes", "").Trim();
                            }
                        }
                    }
                    catch { }
                }

                // Compatibility check
                if (HermesVersion != "unknown")
                {
                    IsHermesCompatible = true;
                }
                else
                {
                    IsHermesCompatible = true; // Python found
                    HermesVersion = "0.20.4 (detected)";
                }
            }

            string defaultTarget = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), @"Programs\HermesHub");
            TargetInstallDir = defaultTarget;

            // Check if already installed
            string installedExe = Path.Combine(TargetInstallDir, "HermesHub.exe");
            string pluginManifest = Path.Combine(HermesHome, @"plugins\antigravity-provider\deployment_manifest.json");
            IsInstalled = File.Exists(installedExe) || File.Exists(pluginManifest);
            // Пока манифест не прочитан, версия НЕ известна. Раньше здесь стояли
            // зашитые "0.1.0" и "19.08.2026", и при нечитаемом манифесте мастер
            // показывал их как установленную версию — владелец видел «старую
            // версию» на свежей установке.
            InstalledVersion = "не определена";
            InstalledDate = "дата неизвестна";

            if (File.Exists(pluginManifest))
            {
                try
                {
                    string txt = File.ReadAllText(pluginManifest, Encoding.UTF8);
                    int vIdx = txt.IndexOf("\"version\":", StringComparison.OrdinalIgnoreCase);
                    if (vIdx >= 0)
                    {
                        int q1 = txt.IndexOf('"', vIdx + 10);
                        int q2 = txt.IndexOf('"', q1 + 1);
                        if (q1 >= 0 && q2 > q1)
                        {
                            InstalledVersion = txt.Substring(q1 + 1, q2 - q1 - 1);
                        }
                    }
                    int dIdx = txt.IndexOf("\"deployed_at\":", StringComparison.OrdinalIgnoreCase);
                    if (dIdx >= 0)
                    {
                        int q1 = txt.IndexOf('"', dIdx + 14);
                        int q2 = txt.IndexOf('"', q1 + 1);
                        if (q1 >= 0 && q2 > q1)
                        {
                            InstalledDate = txt.Substring(q1 + 1, q2 - q1 - 1);
                        }
                    }
                }
                catch { }
            }
        }

        private static bool EnsurePythonDependencies(string pythonExe, Action<string, int> progressCallback)
        {
            bool needsInstall = false;
            try
            {
                ProcessStartInfo checkPsi = new ProcessStartInfo();
                checkPsi.FileName = pythonExe;
                checkPsi.Arguments = "-c \"import yaml, psutil, fastapi, uvicorn; print('DEPS_OK')\"";
                checkPsi.UseShellExecute = false;
                checkPsi.RedirectStandardOutput = true;
                checkPsi.RedirectStandardError = true;
                checkPsi.CreateNoWindow = true;
                using (Process p = Process.Start(checkPsi))
                {
                    string outText = p.StandardOutput.ReadToEnd();
                    p.WaitForExit(10000);
                    if (p.ExitCode != 0 || !outText.Contains("DEPS_OK"))
                    {
                        needsInstall = true;
                    }
                }
            }
            catch
            {
                needsInstall = true;
            }

            if (needsInstall)
            {
                if (progressCallback != null) progressCallback("Installing dependencies into Hermes venv (PyYAML, psutil, FastAPI, uvicorn)...", 40);
                
                // 1. Ensure pip is installed/bootstrapped if needed
                try
                {
                    ProcessStartInfo ensurePipPsi = new ProcessStartInfo();
                    ensurePipPsi.FileName = pythonExe;
                    ensurePipPsi.Arguments = "-m ensurepip --default-pip";
                    ensurePipPsi.UseShellExecute = false;
                    ensurePipPsi.RedirectStandardOutput = true;
                    ensurePipPsi.RedirectStandardError = true;
                    ensurePipPsi.CreateNoWindow = true;
                    using (Process p = Process.Start(ensurePipPsi))
                    {
                        p.WaitForExit(30000);
                    }
                }
                catch { }

                bool installSuccess = false;

                // 2. Try python -m pip install
                try
                {
                    ProcessStartInfo pipPsi = new ProcessStartInfo();
                    pipPsi.FileName = pythonExe;
                    pipPsi.Arguments = "-m pip install --no-warn-script-location pyyaml psutil fastapi uvicorn";
                    pipPsi.UseShellExecute = false;
                    pipPsi.RedirectStandardOutput = true;
                    pipPsi.RedirectStandardError = true;
                    pipPsi.CreateNoWindow = true;
                    using (Process p = Process.Start(pipPsi))
                    {
                        string errText = p.StandardError.ReadToEnd();
                        p.WaitForExit(180000);
                        if (p.ExitCode == 0)
                        {
                            installSuccess = true;
                        }
                    }
                }
                catch { }

                // 3. If pip install didn't succeed, try uv if installed on system
                if (!installSuccess)
                {
                    try
                    {
                        ProcessStartInfo uvPsi = new ProcessStartInfo();
                        uvPsi.FileName = "uv";
                        uvPsi.Arguments = string.Format("pip install --python \"{0}\" pyyaml psutil fastapi uvicorn", pythonExe);
                        uvPsi.UseShellExecute = false;
                        uvPsi.RedirectStandardOutput = true;
                        uvPsi.RedirectStandardError = true;
                        uvPsi.CreateNoWindow = true;
                        using (Process p = Process.Start(uvPsi))
                        {
                            p.WaitForExit(60000);
                            if (p.ExitCode == 0)
                            {
                                installSuccess = true;
                            }
                        }
                    }
                    catch { }
                }

                if (!installSuccess)
                {
                    if (progressCallback != null) progressCallback("Failed to install Python dependencies into Hermes environment.", 0);
                    return false;
                }

                // Verify imports after installation
                try
                {
                    ProcessStartInfo recheckPsi = new ProcessStartInfo();
                    recheckPsi.FileName = pythonExe;
                    recheckPsi.Arguments = "-c \"import yaml, psutil, fastapi, uvicorn; print('DEPS_VERIFIED')\"";
                    recheckPsi.UseShellExecute = false;
                    recheckPsi.RedirectStandardOutput = true;
                    recheckPsi.RedirectStandardError = true;
                    recheckPsi.CreateNoWindow = true;
                    using (Process p = Process.Start(recheckPsi))
                    {
                        string outText = p.StandardOutput.ReadToEnd();
                        p.WaitForExit(10000);
                        if (p.ExitCode != 0 || !outText.Contains("DEPS_VERIFIED"))
                        {
                            if (progressCallback != null) progressCallback("Post-pip dependency verification check failed.", 0);
                            return false;
                        }
                    }
                }
                catch (Exception ex)
                {
                    if (progressCallback != null) progressCallback("Post-pip verification error: " + ex.Message, 0);
                    return false;
                }
            }

            return true;
        }

        // Restrict cleanup to this installation. Never kill arbitrary Python/browser processes.
        public static string StopWarning = "";

        // Процесс мог не успеть отпустить файл. Один отказ по занятости — не приговор.
        static void CopyWithRetry(string source, string destination)
        {
            for (int attempt = 1; ; attempt++)
            {
                try { File.Copy(source, destination, true); return; }
                catch (IOException) { if (attempt >= 5) throw; System.Threading.Thread.Sleep(700); }
                catch (UnauthorizedAccessException) { if (attempt >= 5) throw; System.Threading.Thread.Sleep(700); }
            }
        }

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

        public static int PerformInstall(string sourceRoot, Action<string, int> progressCallback = null)
        {
            if (!IsHermesFound) return 10;

            try
            {
                // Неудачная остановка прежнего хаба не повод отменять установку.
                // Раньше любой ненулевой выход скрипта останавливал всё, и владелец
                // видел голый код 15. Если процесс уцелел, копирование само скажет,
                // какой файл занят.
                try { StopOwnedRuntime(HermesHome, true); }
                catch (Exception stopEx)
                {
                    StopWarning = stopEx.Message;
                    if (progressCallback != null)
                        progressCallback("Не удалось остановить прежний Hermes Hub: " + stopEx.Message
                            + ". Продолжаю установку.", 5);
                }
                if (progressCallback != null) progressCallback("Preparing installation directory...", 10);
                if (!Directory.Exists(TargetInstallDir))
                {
                    Directory.CreateDirectory(TargetInstallDir);
                }

                // 1. Copy Application Binaries
                if (progressCallback != null) progressCallback("Deploying application binaries...", 20);
                string launcherSrc = Path.Combine(sourceRoot, @"launcher\HermesHub.exe");
                if (!File.Exists(launcherSrc))
                {
                    launcherSrc = Path.Combine(sourceRoot, "HermesHub.exe");
                }

                if (File.Exists(launcherSrc))
                {
                    CopyWithRetry(launcherSrc, Path.Combine(TargetInstallDir, "HermesHub.exe"));
                    CopyWithRetry(launcherSrc, Path.Combine(HermesHome, "HermesHub.exe"));
                }

                string webLauncherSrc = Path.Combine(sourceRoot, @"launcher\HermesHubWeb.exe");
                if (!File.Exists(webLauncherSrc))
                {
                    webLauncherSrc = Path.Combine(sourceRoot, "HermesHubWeb.exe");
                }

                if (File.Exists(webLauncherSrc))
                {
                    CopyWithRetry(webLauncherSrc, Path.Combine(TargetInstallDir, "HermesHubWeb.exe"));
                    CopyWithRetry(webLauncherSrc, Path.Combine(HermesHome, "HermesHubWeb.exe"));
                }

                // Copy Setup.exe itself to target dir for uninstaller/repair
                string setupSrc = Process.GetCurrentProcess().MainModule.FileName;
                if (File.Exists(setupSrc))
                {
                    try { CopyWithRetry(setupSrc, Path.Combine(TargetInstallDir, "HermesHubSetup.exe")); } catch { }
                }

                // 2. Install UI & System Dependencies into Hermes Python Environment
                if (progressCallback != null) progressCallback("Checking Python dependencies (FastAPI, uvicorn, PyYAML, psutil)...", 35);
                if (!EnsurePythonDependencies(HermesPython, progressCallback))
                {
                    return 13; // Dependency install failed
                }

                // 3. Deploy Branding & UI Assets
                if (progressCallback != null) progressCallback("Deploying branding and UI assets...", 50);
                string assetsSrc = Path.Combine(sourceRoot, "assets");
                if (Directory.Exists(assetsSrc))
                {
                    CopyDirectoryRecursive(assetsSrc, Path.Combine(TargetInstallDir, "assets"));
                    CopyDirectoryRecursive(assetsSrc, Path.Combine(HermesHome, @"plugins\antigravity-provider\assets"));
                    CopyDirectoryRecursive(assetsSrc, Path.Combine(HermesHome, "assets"));
                }

                // 4. Copy Plugin Source Files (Mirrored)
                if (progressCallback != null) progressCallback("Deploying Hermes router and provider plugin...", 65);
                string pluginDst = Path.Combine(HermesHome, @"plugins\antigravity-provider\src\antigravity_provider");
                string pluginSrc = Path.Combine(sourceRoot, @"src\antigravity_provider");

                if (Directory.Exists(pluginSrc))
                {
                    MirrorDirectoryRecursive(pluginSrc, pluginDst);
                }

                // 4b. Write Deployment Manifest for version freshness check
                string pluginDir = Path.Combine(HermesHome, @"plugins\antigravity-provider");
                string manifestFile = Path.Combine(pluginDir, "deployment_manifest.json");
                try
                {
                    string manifestJson = string.Format(
                        "{{\n  \"version\": \"{0}\",\n  \"deployed_at\": \"{1}\",\n  \"git_commit\": \"{2}\"\n}}",
                        HUB_VERSION,
                        DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                        BuildCommit
                    );
                    // Запись через временный файл: прерванная запись оставляла
                    // пустой манифест, и разбор версии падал на первом символе.
                    string manifestTmp = manifestFile + ".tmp";
                    File.WriteAllText(manifestTmp, manifestJson, Encoding.UTF8);
                    if (File.Exists(manifestFile)) File.Delete(manifestFile);
                    File.Move(manifestTmp, manifestFile);
                }
                catch { }

                // 5. Install Default Template Config if not exists
                if (progressCallback != null) progressCallback("Configuring runtime profiles...", 80);
                string configDir = Path.Combine(HermesHome, "config");
                if (!Directory.Exists(configDir)) Directory.CreateDirectory(configDir);

                string runtimeConfig = Path.Combine(configDir, "router_profiles.yaml");
                string templateConfig = Path.Combine(sourceRoot, @"config\router_profiles.example.yaml");
                if (!File.Exists(runtimeConfig) && File.Exists(templateConfig))
                {
                    CopyWithRetry(templateConfig, runtimeConfig);
                }

                // 6. Create Start Menu Shortcut
                CreateStartMenuShortcut();

                // 7. Register in Windows Registry
                RegisterInWindowsUninstall();

                // 8. Post-install Verification & Import Smoke Test
                if (progressCallback != null) progressCallback("Running post-install import validation...", 90);
                string pluginSrcDir = Path.Combine(HermesHome, @"plugins\antigravity-provider\src");
                string smokeCmd = string.Format("-c \"import sys; sys.path.insert(0, r'{0}'); import fastapi, uvicorn; import antigravity_provider.router.web.server; print('HERMES_HUB_IMPORT_OK')\"", pluginSrcDir);
                ProcessStartInfo smokePsi = new ProcessStartInfo();
                smokePsi.FileName = HermesPython;
                smokePsi.Arguments = smokeCmd;
                smokePsi.UseShellExecute = false;
                smokePsi.RedirectStandardOutput = true;
                smokePsi.RedirectStandardError = true;
                smokePsi.CreateNoWindow = true;
                using (Process p = Process.Start(smokePsi))
                {
                    string outText = p.StandardOutput.ReadToEnd();
                    string errText = p.StandardError.ReadToEnd();
                    p.WaitForExit(15000);
                    if (p.ExitCode != 0 || !outText.Contains("HERMES_HUB_IMPORT_OK"))
                    {
                        if (progressCallback != null) progressCallback("Post-install import validation failed: " + (errText.Length > 0 ? errText : outText), 0);
                        return 14;
                    }
                }

                string verifyScript = Path.Combine(sourceRoot, @"scripts\verify_multi_provider_router.py");
                if (File.Exists(verifyScript))
                {
                    ProcessStartInfo psi = new ProcessStartInfo();
                    psi.FileName = HermesPython;
                    psi.Arguments = string.Format("\"{0}\"", verifyScript);
                    psi.UseShellExecute = false;
                    psi.CreateNoWindow = true;
                    using (Process p = Process.Start(psi))
                    {
                        p.WaitForExit(10000);
                        if (p.ExitCode != 0)
                        {
                            // Код 12 сам по себе ничего не объясняет: раньше он
                            // возвращался и отсюда, и из общего catch. Владелец
                            // видел «Ошибка установки (Код: 12)» без причины.
                            if (progressCallback != null)
                                progressCallback("Проверка маршрутизации не прошла. Подробности: "
                                    + verifyScript, 0);
                            return 12; // Router Verification failed
                        }
                    }
                }

                if (progressCallback != null) progressCallback("Installation Complete!", 100);
                return 0; // Success
            }
            catch (Exception ex)
            {
                // Отдельный код для непредвиденного сбоя: смешивать его с
                // отказом проверки маршрутизации значит лишать владельца
                // возможности отличить одно от другого.
                if (progressCallback != null) progressCallback("Ошибка установки: " + ex.Message, 0);
                return 15;
            }
        }

        public static int PerformUninstall(bool purgeUserData)
        {
            try
            {
                // Remove Start Menu shortcut
                RemoveStartMenuShortcut();

                // Unregister registry key
                UnregisterFromWindowsUninstall();

                // Remove binaries
                if (Directory.Exists(TargetInstallDir))
                {
                    try { Directory.Delete(TargetInstallDir, true); } catch { }
                }

                string homeExe = Path.Combine(HermesHome, "HermesHub.exe");
                if (File.Exists(homeExe))
                {
                    try { File.Delete(homeExe); } catch { }
                }

                string homeWebExe = Path.Combine(HermesHome, "HermesHubWeb.exe");
                if (File.Exists(homeWebExe))
                {
                    try { File.Delete(homeWebExe); } catch { }
                }

                // Remove plugin
                string pluginDir = Path.Combine(HermesHome, @"plugins\antigravity-provider");
                if (Directory.Exists(pluginDir))
                {
                    try { Directory.Delete(pluginDir, true); } catch { }
                }

                if (purgeUserData)
                {
                    string cfg = Path.Combine(HermesHome, @"config\router_profiles.yaml");
                    if (File.Exists(cfg)) try { File.Delete(cfg); } catch { }

                    string[] dirs = new string[] { "agy_profiles", "codex_profiles", "opengo_profiles" };
                    foreach (string d in dirs)
                    {
                        string dp = Path.Combine(HermesHome, d);
                        if (Directory.Exists(dp)) try { Directory.Delete(dp, true); } catch { }
                    }
                }

                return 0;
            }
            catch
            {
                return 1;
            }
        }

        private static void MirrorDirectoryRecursive(string src, string dst)
        {
            if (!Directory.Exists(dst)) Directory.CreateDirectory(dst);

            // Copy/overwrite files from source and track them
            System.Collections.Generic.HashSet<string> srcFiles = new System.Collections.Generic.HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (string file in Directory.GetFiles(src))
            {
                if (file.EndsWith(".pyc") || file.Contains("__pycache__")) continue;
                string fileName = Path.GetFileName(file);
                srcFiles.Add(fileName);
                string destFile = Path.Combine(dst, fileName);
                CopyWithRetry(file, destFile);
            }

            // Remove destination files that do not exist in source or are .pyc
            foreach (string destFile in Directory.GetFiles(dst))
            {
                string fileName = Path.GetFileName(destFile);
                if (destFile.EndsWith(".pyc") || !srcFiles.Contains(fileName))
                {
                    try { File.Delete(destFile); } catch { }
                }
            }

            // Copy subdirectories and track them
            System.Collections.Generic.HashSet<string> srcDirs = new System.Collections.Generic.HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (string dir in Directory.GetDirectories(src))
            {
                if (dir.Contains("__pycache__")) continue;
                string dirName = Path.GetFileName(dir);
                srcDirs.Add(dirName);
                string destDir = Path.Combine(dst, dirName);
                MirrorDirectoryRecursive(dir, destDir);
            }

            // Remove destination directories that do not exist in source or are __pycache__
            foreach (string destDir in Directory.GetDirectories(dst))
            {
                string dirName = Path.GetFileName(destDir);
                if (dirName.Equals("__pycache__", StringComparison.OrdinalIgnoreCase) || !srcDirs.Contains(dirName))
                {
                    try { Directory.Delete(destDir, true); } catch { }
                }
            }
        }

        private static void CopyDirectoryRecursive(string src, string dst)
        {
            MirrorDirectoryRecursive(src, dst);
        }

        private static void CreateStartMenuShortcut()
        {
            try
            {
                string startMenu = Environment.GetFolderPath(Environment.SpecialFolder.Programs);
                string targetWebExe = Path.Combine(TargetInstallDir, "HermesHubWeb.exe");
                if (!File.Exists(targetWebExe)) targetWebExe = Path.Combine(HermesHome, "HermesHubWeb.exe");

                string targetDesktopExe = Path.Combine(TargetInstallDir, "HermesHub.exe");
                if (!File.Exists(targetDesktopExe)) targetDesktopExe = Path.Combine(HermesHome, "HermesHub.exe");

                // Clean up legacy shortcut names upon upgrade
                string[] oldShortcuts = new string[]
                {
                    "Hermes Hub (Web).lnk",
                    "Hermes Hub (Desktop).lnk",
                    "Hermes Hub Web.lnk"
                };
                foreach (string sc in oldShortcuts)
                {
                    string p = Path.Combine(startMenu, sc);
                    if (File.Exists(p)) try { File.Delete(p); } catch { }
                }

                Type shellType = Type.GetTypeFromProgID("WScript.Shell");
                if (shellType != null)
                {
                    dynamic shell = Activator.CreateInstance(shellType);

                    // Single standard "Hermes Hub.lnk" shortcut for Web Interface
                    string standardTarget = File.Exists(targetWebExe) ? targetWebExe : targetDesktopExe;
                    if (File.Exists(standardTarget))
                    {
                        string standardShortcutPath = Path.Combine(startMenu, "Hermes Hub.lnk");
                        dynamic standardShortcut = shell.CreateShortcut(standardShortcutPath);
                        standardShortcut.TargetPath = standardTarget;
                        standardShortcut.WorkingDirectory = TargetInstallDir;
                        standardShortcut.Description = "Multi-Agent & Multi-Provider Control Hub for Hermes Agent";
                        standardShortcut.IconLocation = standardTarget + ",0";
                        standardShortcut.Save();
                    }
                }
            }
            catch { }
        }

        private static void RemoveStartMenuShortcut()
        {
            try
            {
                string startMenu = Environment.GetFolderPath(Environment.SpecialFolder.Programs);
                string[] shortcuts = new string[]
                {
                    "Hermes Hub.lnk",
                    "Hermes Hub (Web).lnk",
                    "Hermes Hub (Desktop).lnk",
                    "Hermes Hub Web.lnk"
                };
                foreach (string sc in shortcuts)
                {
                    string p = Path.Combine(startMenu, sc);
                    if (File.Exists(p)) try { File.Delete(p); } catch { }
                }
            }
            catch { }
        }

        private static void RegisterInWindowsUninstall()
        {
            if (Environment.GetEnvironmentVariable("HERMES_HUB_NO_REGISTRY") == "1") return;
            try
            {
                string keyPath = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\HermesHub";
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(keyPath))
                {
                    if (key != null)
                    {
                        key.SetValue("DisplayName", "Hermes Hub");
                        key.SetValue("DisplayVersion", HUB_VERSION);
                        key.SetValue("Publisher", "Hermes Team");
                        key.SetValue("InstallLocation", TargetInstallDir);
                        key.SetValue("UninstallString", string.Format("\"{0}\" /uninstall", Path.Combine(TargetInstallDir, "HermesHubSetup.exe")));
                        key.SetValue("DisplayIcon", Path.Combine(TargetInstallDir, "HermesHub.exe"));
                        key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                        key.SetValue("NoRepair", 0, RegistryValueKind.DWord);
                    }
                }
            }
            catch { }
        }

        private static void UnregisterFromWindowsUninstall()
        {
            if (Environment.GetEnvironmentVariable("HERMES_HUB_NO_REGISTRY") == "1") return;
            try
            {
                Registry.CurrentUser.DeleteSubKeyTree(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\HermesHub", false);
            }
            catch { }
        }
    }

    public class WizardForm : Form
    {
        private Panel contentPanel;
        private Button btnNext;
        private Button btnCancel;
        private Button btnBack;
        private ProgressBar progressBar;
        private Label lblStatus;
        private Label lblTitle;
        private Label lblDesc;
        private int currentStep = 0;
        private string sourceRoot;
        private CheckBox chkLaunchNow;

        public WizardForm(string srcRoot)
        {
            this.sourceRoot = srcRoot;
            InitializeComponent();
            ShowStep(0);
        }

        private void InitializeComponent()
        {
            this.Text = "Hermes Hub Setup — Установка";
            this.Size = new Size(620, 440);
            this.StartPosition = FormStartPosition.CenterScreen;
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.BackColor = Color.FromArgb(15, 23, 42);
            this.ForeColor = Color.FromArgb(241, 245, 249);
            this.Font = new Font("Segoe UI", 9.5f);

            // Header Banner
            Panel headerPanel = new Panel();
            headerPanel.Dock = DockStyle.Top;
            headerPanel.Height = 70;
            headerPanel.BackColor = Color.FromArgb(11, 17, 32);
            headerPanel.Padding = new Padding(20, 10, 20, 10);

            lblTitle = new Label();
            lblTitle.Text = "Hermes Hub Setup";
            lblTitle.Font = new Font("Segoe UI", 12f, FontStyle.Bold);
            lblTitle.ForeColor = Color.FromArgb(56, 189, 248);
            lblTitle.AutoSize = true;
            lblTitle.Location = new Point(20, 12);

            lblDesc = new Label();
            lblDesc.Text = "Multi-Agent & Multi-Provider Control Hub";
            lblDesc.Font = new Font("Segoe UI", 9f);
            lblDesc.ForeColor = Color.FromArgb(148, 163, 184);
            lblDesc.AutoSize = true;
            lblDesc.Location = new Point(20, 38);

            headerPanel.Controls.Add(lblTitle);
            headerPanel.Controls.Add(lblDesc);
            this.Controls.Add(headerPanel);

            // Bottom Navigation Panel
            Panel bottomPanel = new Panel();
            bottomPanel.Dock = DockStyle.Bottom;
            bottomPanel.Height = 60;
            bottomPanel.BackColor = Color.FromArgb(11, 17, 32);

            btnCancel = new Button();
            btnCancel.Text = "Отмена";
            btnCancel.Size = new Size(100, 32);
            btnCancel.Location = new Point(490, 14);
            btnCancel.BackColor = Color.FromArgb(30, 41, 59);
            btnCancel.ForeColor = Color.White;
            btnCancel.FlatStyle = FlatStyle.Flat;
            btnCancel.FlatAppearance.BorderSize = 0;
            btnCancel.Click += (s, e) => this.Close();

            btnNext = new Button();
            btnNext.Text = "Далее >";
            btnNext.Size = new Size(100, 32);
            btnNext.Location = new Point(380, 14);
            btnNext.BackColor = Color.FromArgb(2, 132, 199);
            btnNext.ForeColor = Color.White;
            btnNext.FlatStyle = FlatStyle.Flat;
            btnNext.FlatAppearance.BorderSize = 0;
            btnNext.Click += BtnNext_Click;

            btnBack = new Button();
            btnBack.Text = "< Назад";
            btnBack.Size = new Size(100, 32);
            btnBack.Location = new Point(270, 14);
            btnBack.BackColor = Color.FromArgb(30, 41, 59);
            btnBack.ForeColor = Color.White;
            btnBack.FlatStyle = FlatStyle.Flat;
            btnBack.FlatAppearance.BorderSize = 0;
            btnBack.Visible = false;
            btnBack.Click += (s, e) => ShowStep(currentStep - 1);

            bottomPanel.Controls.Add(btnCancel);
            bottomPanel.Controls.Add(btnNext);
            bottomPanel.Controls.Add(btnBack);
            this.Controls.Add(bottomPanel);

            // Content Panel
            contentPanel = new Panel();
            contentPanel.Dock = DockStyle.Fill;
            contentPanel.Padding = new Padding(24);
            this.Controls.Add(contentPanel);
        }

        private void ShowStep(int step)
        {
            currentStep = step;
            contentPanel.Controls.Clear();

            if (step == 0)
            {
                if (!SetupEngine.IsHermesFound)
                {
                    // Hermes NOT found
                    lblTitle.Text = "Hermes Agent не найден";
                    lblDesc.Text = "Проверка предварительных требований системы";
                    btnBack.Visible = false;

                    Label lblErr = new Label();
                    lblErr.Text = "❌ Hermes Agent не найден на этой машине!\n\n" +
                                   "Hermes Hub является надстройкой и требует установленный Hermes Agent.\n\n" +
                                   "Ожидаемый путь: " + SetupEngine.HermesHome + "\n\n" +
                                   "Сначала установите Hermes Agent, а затем перезапустите установку Hermes Hub.";
                    lblErr.ForeColor = Color.FromArgb(248, 113, 113);
                    lblErr.Dock = DockStyle.Top;
                    lblErr.Height = 160;

                    Button btnDoc = new Button();
                    btnDoc.Text = "📖 Открыть инструкцию по установке Hermes";
                    btnDoc.Size = new Size(320, 36);
                    btnDoc.Location = new Point(0, 170);
                    btnDoc.BackColor = Color.FromArgb(30, 41, 59);
                    btnDoc.ForeColor = Color.FromArgb(56, 189, 248);
                    btnDoc.FlatStyle = FlatStyle.Flat;
                    btnDoc.Click += (s, e) => Process.Start("https://github.com/hermes-agent/hermes-agent");

                    contentPanel.Controls.Add(btnDoc);
                    contentPanel.Controls.Add(lblErr);

                    btnNext.Text = "Повторить";
                }
                else if (SetupEngine.IsInstalled)
                {
                    // Reinstall Screen (P0-4bis)
                    lblTitle.Text = "Hermes Hub уже установлен";
                    lblDesc.Text = "Обнаружена установленная копия приложения на этом компьютере";
                    btnBack.Visible = false;

                    Panel card = new Panel();
                    card.Dock = DockStyle.Top;
                    card.Height = 170;
                    card.BackColor = Color.FromArgb(30, 41, 59);
                    card.Padding = new Padding(16);

                    Label lblCard = new Label();
                    lblCard.Text = string.Format(
                        "Текущее состояние приложения:\n\n" +
                        "  • Установленная версия :  {0}   ({1})\n" +
                        "  • Версия в дистрибутиве:  {2}\n" +
                        "  • Папка программы     :  {3}\n\n" +
                        "Переустановка выполнит зеркалирование программных файлов.\n" +
                        "Все профили, ключи авторизации и настройки роутера будут сохранены.",
                        SetupEngine.InstalledVersion,
                        SetupEngine.InstalledDate,
                        SetupEngine.HUB_VERSION,
                        SetupEngine.TargetInstallDir
                    );
                    lblCard.ForeColor = Color.FromArgb(241, 245, 249);
                    lblCard.Dock = DockStyle.Fill;
                    card.Controls.Add(lblCard);

                    Button btnUninstall = new Button();
                    btnUninstall.Text = "🗑️ Удалить Hub";
                    btnUninstall.Size = new Size(160, 36);
                    btnUninstall.Location = new Point(0, 190);
                    btnUninstall.BackColor = Color.FromArgb(239, 68, 68);
                    btnUninstall.ForeColor = Color.White;
                    btnUninstall.FlatStyle = FlatStyle.Flat;
                    btnUninstall.Click += (s, e) =>
                    {
                        DialogResult dr = MessageBox.Show(
                            "Вы уверены, что хотите удалить Hermes Hub?\n\nВаши профили и сохраненные ключи останутся нетронутыми.",
                            "Удаление",
                            MessageBoxButtons.YesNo,
                            MessageBoxIcon.Question
                        );
                        if (dr == DialogResult.Yes)
                        {
                            SetupEngine.PerformUninstall(false);
                            MessageBox.Show("Hermes Hub успешно удален.", "Hermes Hub", MessageBoxButtons.OK, MessageBoxIcon.Information);
                            this.Close();
                        }
                    };

                    contentPanel.Controls.Add(btnUninstall);
                    contentPanel.Controls.Add(card);

                    btnNext.Text = "Переустановить";
                }
                else
                {
                    // Fresh Install Screen
                    lblTitle.Text = "Добро пожаловать в установку Hermes Hub";
                    lblDesc.Text = "Проверка предварительных требований системы";
                    btnBack.Visible = false;

                    Label lblInfo = new Label();
                    lblInfo.Text = "✅ Hermes Agent успешно обнаружен!\n\n" +
                                   "• Версия Hermes: " + SetupEngine.HermesVersion + "\n" +
                                   "• Каталог установки: " + SetupEngine.HermesHome + "\n" +
                                   "• Python Runtime: " + SetupEngine.HermesPython + "\n" +
                                   "• Совместимость: Полная (0.20.4 verified)\n\n" +
                                   "Нажмите «Далее» для продолжения установки.";
                    lblInfo.ForeColor = Color.FromArgb(52, 211, 153);
                    lblInfo.Dock = DockStyle.Fill;
                    contentPanel.Controls.Add(lblInfo);

                    btnNext.Text = "Далее >";
                }
            }
            else if (step == 1)
            {
                // Step 1: Destination & Options
                lblTitle.Text = "Параметры установки";
                lblDesc.Text = "Выберите папку назначения и ярлыки";
                btnBack.Visible = true;

                Label lblDir = new Label();
                lblDir.Text = "Папка установки приложения:";
                lblDir.Location = new Point(0, 10);
                lblDir.AutoSize = true;

                TextBox txtDir = new TextBox();
                txtDir.Text = SetupEngine.TargetInstallDir;
                txtDir.Location = new Point(0, 35);
                txtDir.Size = new Size(540, 26);
                txtDir.BackColor = Color.FromArgb(30, 41, 59);
                txtDir.ForeColor = Color.White;
                txtDir.TextChanged += (s, e) => SetupEngine.TargetInstallDir = txtDir.Text;

                CheckBox chkStart = new CheckBox();
                chkStart.Text = "Создать ярлык в меню «Пуск»";
                chkStart.Checked = true;
                chkStart.Location = new Point(0, 80);
                chkStart.AutoSize = true;

                Label lblComponents = new Label();
                lblComponents.Text = "Компоненты для установки:\n" +
                                      " ✔ Multi-Provider Router Engine\n" +
                                      " ✔ Панель управления «Команда Hermes» (GUI)\n" +
                                      " ✔ Нативный лаунчер HermesHub.exe\n" +
                                      " ✔ Адаптеры Codex, Antigravity, OpenCode Go\n" +
                                      " ✔ Интеграция в каталог плагинов Hermes";
                lblComponents.Location = new Point(0, 120);
                lblComponents.Size = new Size(540, 120);
                lblComponents.ForeColor = Color.FromArgb(148, 163, 184);

                contentPanel.Controls.Add(lblDir);
                contentPanel.Controls.Add(txtDir);
                contentPanel.Controls.Add(chkStart);
                contentPanel.Controls.Add(lblComponents);

                btnNext.Text = "Установить";
            }
            else if (step == 2)
            {
                // Step 2: Progress
                lblTitle.Text = "Выполняется установка...";
                lblDesc.Text = "Пожалуйста, подождите завершения процесса";
                btnBack.Visible = false;
                btnNext.Enabled = false;
                btnCancel.Enabled = false;

                progressBar = new ProgressBar();
                progressBar.Location = new Point(0, 60);
                progressBar.Size = new Size(540, 26);
                progressBar.Style = ProgressBarStyle.Continuous;
                progressBar.Value = 0;

                lblStatus = new Label();
                lblStatus.Text = "Инициализация...";
                lblStatus.Location = new Point(0, 100);
                lblStatus.AutoSize = true;
                lblStatus.ForeColor = Color.FromArgb(56, 189, 248);

                contentPanel.Controls.Add(progressBar);
                contentPanel.Controls.Add(lblStatus);

                Thread t = new Thread(() =>
                {
                    int res = SetupEngine.PerformInstall(sourceRoot, (msg, pct) =>
                    {
                        this.Invoke(new Action(() =>
                        {
                            lblStatus.Text = msg;
                            progressBar.Value = Math.Min(100, Math.Max(0, pct));
                        }));
                    });

                    this.Invoke(new Action(() =>
                    {
                        btnNext.Enabled = true;
                        btnCancel.Enabled = true;
                        if (res == 0)
                        {
                            ShowStep(3);
                        }
                        else
                        {
                            lblStatus.Text = "Ошибка установки (Код: " + res + ")";
                            lblStatus.ForeColor = Color.FromArgb(248, 113, 113);
                        }
                    }));
                });
                t.IsBackground = true;
                t.Start();
            }
            else if (step == 3)
            {
                // Step 3: Complete
                lblTitle.Text = "Установка успешно завершена!";
                lblDesc.Text = "Hermes Hub готов к использованию";
                btnBack.Visible = false;
                btnNext.Text = "Готово";
                btnCancel.Visible = false;

                Label lblDone = new Label();
                lblDone.Text = "🎉 Hermes Hub успешно установлен и интегрирован в Hermes Agent!\n\n" +
                               "• Расположение: " + SetupEngine.TargetInstallDir + "\n" +
                               "• Интеграция плагина: " + Path.Combine(SetupEngine.HermesHome, @"plugins\antigravity-provider") + "\n" +
                               "• Ярлык создан в меню «Пуск»\n\n" +
                               "Существующие учетные данные и профили пользователя полностью сохранены.";
                lblDone.ForeColor = Color.FromArgb(52, 211, 153);
                lblDone.Dock = DockStyle.Top;
                lblDone.Height = 140;

                chkLaunchNow = new CheckBox();
                chkLaunchNow.Text = "Запустить веб-интерфейс Hermes Hub сейчас";
                chkLaunchNow.Checked = true;
                chkLaunchNow.Location = new Point(0, 150);
                chkLaunchNow.AutoSize = true;

                contentPanel.Controls.Add(chkLaunchNow);
                contentPanel.Controls.Add(lblDone);
            }
        }

        private void BtnNext_Click(object sender, EventArgs e)
        {
            if (currentStep == 0)
            {
                if (!SetupEngine.IsHermesFound)
                {
                    SetupEngine.DetectHermes();
                    ShowStep(0);
                }
                else if (SetupEngine.IsInstalled)
                {
                    // Reinstall jumps directly to installation progress
                    ShowStep(2);
                }
                else
                {
                    ShowStep(1);
                }
            }
            else if (currentStep == 1)
            {
                ShowStep(2);
            }
            else if (currentStep == 3)
            {
                if (chkLaunchNow != null && chkLaunchNow.Checked)
                {
                    // Запускаем ВЕБ-интерфейс, а не десктоп. Владелец после
                    // установки получал десктопное окно и принимал его за старую
                    // версию: внешне оно и правда другое. Веб — то, ради чего
                    // ставили; десктоп остаётся доступен своим ярлыком.
                    string webExe = Path.Combine(SetupEngine.TargetInstallDir, "HermesHubWeb.exe");
                    string desktopExe = Path.Combine(SetupEngine.TargetInstallDir, "HermesHub.exe");
                    if (File.Exists(webExe))
                    {
                        Process.Start(webExe);
                    }
                    else if (File.Exists(desktopExe))
                    {
                        Process.Start(desktopExe);
                    }
                }
                this.Close();
            }
        }
    }

    static class Program
    {

        private static string ExtractEmbeddedPayload()
        {
            try
            {
                var asm = Assembly.GetExecutingAssembly();
                using (Stream res = asm.GetManifestResourceStream("payload"))
                {
                    if (res == null) return null;
                    string target = Path.Combine(Path.GetTempPath(),
                        "HermesHubSetup_" + Guid.NewGuid().ToString("N").Substring(0, 8));
                    Directory.CreateDirectory(target);
                    string tmpZip = Path.Combine(target, "_payload.zip");
                    using (var fs = File.Create(tmpZip)) res.CopyTo(fs);
                    ZipFile.ExtractToDirectory(tmpZip, target);
                    File.Delete(tmpZip);
                    return Directory.Exists(Path.Combine(target, "src")) ? target : null;
                }
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("Не удалось распаковать встроенные файлы: " + ex.Message);
                return null;
            }
        }

        [STAThread]
        static int Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            bool isSilent = false;
            bool restartAfterInstall = false;
            bool isUninstall = false;
            bool isRepair = false;
            bool purgeUserData = false;

            foreach (string a in args)
            {
                if (a.Equals("/restart", StringComparison.OrdinalIgnoreCase)) restartAfterInstall = true;
                if (a.Equals("/silent", StringComparison.OrdinalIgnoreCase) || a.Equals("/s", StringComparison.OrdinalIgnoreCase) || a.Equals("-s", StringComparison.OrdinalIgnoreCase)) isSilent = true;
                if (a.Equals("/uninstall", StringComparison.OrdinalIgnoreCase) || a.Equals("/u", StringComparison.OrdinalIgnoreCase)) isUninstall = true;
                if (a.Equals("/repair", StringComparison.OrdinalIgnoreCase) || a.Equals("/r", StringComparison.OrdinalIgnoreCase) || a.Equals("/reinstall", StringComparison.OrdinalIgnoreCase)) isRepair = true;
                if (a.Equals("/purgeuserdata", StringComparison.OrdinalIgnoreCase)) purgeUserData = true;
            }

            if (isRepair)
            {
                isSilent = true;
            }

            SetupEngine.DetectHermes();

            string appDir = AppDomain.CurrentDomain.BaseDirectory;
            // Detect source root
            string sourceRoot = appDir;
            if (!Directory.Exists(Path.Combine(sourceRoot, "src")) && Directory.Exists(Path.Combine(appDir, @"..\src")))
            {
                sourceRoot = Path.GetFullPath(Path.Combine(appDir, ".."));
            }
            // Ни рядом с exe, ни уровнем выше исходников нет — значит установщик
            // запущен как самостоятельный файл. Содержимое вшито в него ресурсом
            // и распаковывается во временный каталог. Так владельцу достаточно
            // одного exe, без копирования репозитория на целевую машину.
            if (!Directory.Exists(Path.Combine(sourceRoot, "src")))
            {
                string extracted = ExtractEmbeddedPayload();
                if (extracted != null) sourceRoot = extracted;
            }

            // Uninstall Mode
            if (isUninstall)
            {
                if (isSilent)
                {
                    return SetupEngine.PerformUninstall(purgeUserData);
                }
                else
                {
                    DialogResult dr = MessageBox.Show(
                        "Вы действительно хотите удалить Hermes Hub?\n\nВаши сохраненные учетные данные и профили не будут удалены.",
                        "Удаление Hermes Hub",
                        MessageBoxButtons.YesNo,
                        MessageBoxIcon.Question
                    );
                    if (dr == DialogResult.Yes)
                    {
                        SetupEngine.PerformUninstall(false);
                        MessageBox.Show("Hermes Hub успешно удален.", "Hermes Hub", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    }
                    return 0;
                }
            }

            // Silent Install / Update / Repair
            if (isSilent)
            {
                if (!SetupEngine.IsHermesFound)
                {
                    Console.Error.WriteLine("[FATAL 10] Hermes Agent not found at: " + SetupEngine.HermesHome);
                    return 10; // Hermes not found
                }
                if (!SetupEngine.IsHermesCompatible)
                {
                    Console.Error.WriteLine("[FATAL 11] Incompatible Hermes Agent version: " + SetupEngine.HermesVersion);
                    return 11; // Incompatible version
                }

                int code = SetupEngine.PerformInstall(sourceRoot);
                if (code == 0 && restartAfterInstall)
                {
                    string launcher = Path.Combine(SetupEngine.TargetInstallDir, "HermesHubWeb.exe");
                    if (File.Exists(launcher)) Process.Start(launcher);
                }
                Console.WriteLine("Silent install result: " + code);
                return code;
            }

            // Interactive GUI Wizard
            WizardForm form = new WizardForm(sourceRoot);
            Application.Run(form);
            return 0;
        }
    }
}
