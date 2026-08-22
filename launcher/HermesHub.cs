using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

namespace HermesHub
{
    static class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            Application.EnableVisualStyles();

            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string hermesHome = Path.Combine(localAppData, "hermes");

            // Prefer pythonw.exe (no console flash) with UseShellExecute=true
            // so tkinter can create GUI windows properly.
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

            // Build sys.path and launch native GUI
            string pluginSrc = Path.Combine(hermesHome, @"plugins\antigravity-provider\src");
            string agentDir = Path.Combine(hermesHome, "hermes-agent");
            string hubSrc = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, @"..\src"));

            StringBuilder script = new StringBuilder();
            script.AppendLine("import sys");
            if (Directory.Exists(pluginSrc))
                script.AppendLine("sys.path.insert(0, r'" + pluginSrc.Replace('\\', '/') + "')");
            if (Directory.Exists(agentDir))
                script.AppendLine("sys.path.insert(0, r'" + agentDir.Replace('\\', '/') + "')");
            if (Directory.Exists(hubSrc))
                script.AppendLine("sys.path.insert(0, r'" + hubSrc.Replace('\\', '/') + "')");
            script.AppendLine("from antigravity_provider.router.launcher_bootstrap import bootstrap_and_launch");
            script.AppendLine("bootstrap_and_launch()");

            string entryScript = Path.Combine(hermesHome, "hermes_hub_entry.py");
            try
            {
                File.WriteAllText(entryScript, script.ToString(), Encoding.UTF8);
            }
            catch (Exception ex)
            {
                MessageBox.Show("Cannot write entry script:\n" + ex.Message, "Hermes Hub", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }

            // UseShellExecute=true is required for tkinter to display GUI windows.
            // WindowStyle=Hidden hides the console (if python.exe is used instead of pythonw.exe).
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = exe;
            psi.Arguments = "\"" + entryScript + "\"";
            psi.WorkingDirectory = hermesHome;
            psi.UseShellExecute = true;
            psi.WindowStyle = ProcessWindowStyle.Hidden;

            try
            {
                Process.Start(psi);
            }
            catch (Exception ex)
            {
                MessageBox.Show("Failed to start Hermes Hub:\n" + ex.Message, "Hermes Hub", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
    }
}
