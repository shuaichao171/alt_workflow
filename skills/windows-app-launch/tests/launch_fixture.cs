using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Windows.Forms;

class LaunchFixture {
    static string Value(string[] args, string name, string fallback) {
        int index = Array.IndexOf(args, name);
        return index >= 0 && index + 1 < args.Length ? args[index + 1] : fallback;
    }
    static Form Window(string title) {
        return new Form { Text = title, Width = 320, Height = 130, StartPosition = FormStartPosition.Manual,
            Location = new Point(80, 80), ShowInTaskbar = true };
    }
    class Context : ApplicationContext {
        readonly System.Windows.Forms.Timer timer;
        public Context(string mode, string signal) {
            MainForm = Window("Workflow launch test");
            MainForm.Show();
            if (mode == "reuse-server") {
                timer = new System.Windows.Forms.Timer { Interval = 100 };
                timer.Tick += delegate {
                    if (!File.Exists(signal)) return;
                    File.Delete(signal);
                    Window("Workflow new window in existing process").Show();
                };
                timer.Start();
                return;
            }
            if (mode != "recreate") return;
            timer = new System.Windows.Forms.Timer { Interval = 350 };
            timer.Tick += delegate {
                timer.Stop();
                Form splash = MainForm;
                MainForm = Window("Workflow replacement window");
                MainForm.Show();
                splash.Close();
                splash.Dispose();
            };
            timer.Start();
        }
    }
    [STAThread]
    static void Main(string[] args) {
        string record = Value(args, "--record", null);
        if (record != null) File.WriteAllLines(record, Array.ConvertAll(args, s => Convert.ToBase64String(Encoding.UTF8.GetBytes(s))));
        string mode = Value(args, "--mode", "single");
        string signal = Value(args, "--signal", null);
        if (mode == "reuse-client") { File.WriteAllText(signal, "open"); return; }
        if (mode == "headless") { Thread.Sleep(2500); return; }
        if (mode == "detach") {
            string child = Value(args, "--child-exe", Assembly.GetExecutingAssembly().Location);
            Process.Start(new ProcessStartInfo { FileName = child, Arguments = "--mode single", UseShellExecute = false });
            return;
        }
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new Context(mode, signal));
    }
}
