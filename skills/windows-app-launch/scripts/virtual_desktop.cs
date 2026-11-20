// Windows 10 22H2 COM interface layout checked against:
// https://github.com/MScholtes/VirtualDesktop/blob/master/VirtualDesktop.cs
// This workflow adapter enumerates desktops, creates a missing destination,
// and moves only explicitly matched windows created for the current launch.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace AltWorkflow.DesktopLaunch {
    [ComImport, Guid("A5CD92FF-29BE-454C-8D04-D82879FB3F1B"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPublicDesktopManager {
        [PreserveSig] int IsWindowOnCurrentVirtualDesktop(IntPtr window, [MarshalAs(UnmanagedType.Bool)] out bool current);
        [PreserveSig] int GetWindowDesktopId(IntPtr window, out Guid desktop);
        [PreserveSig] int MoveWindowToDesktop(IntPtr window, ref Guid desktop);
    }
    public class ProcessRecord {
        public int ProcessId;
        public string ExecutablePath;
        public DateTime StartedUtc;
        public string Key { get { return ProcessId.ToString() + ":" + StartedUtc.Ticks.ToString(); } }
    }
    public class WindowRecord {
        public long Handle;
        public int ProcessId;
        public string ExecutablePath;
        public DateTime StartedUtc;
        public bool Visible;
        public long Owner;
        public bool ToolWindow;
        public string ProcessKey { get { return ProcessId.ToString() + ":" + StartedUtc.Ticks.ToString(); } }
        public string Key { get { return Handle.ToString() + ":" + ProcessKey; } }
    }
    public class WindowSnapshot {
        public ProcessRecord[] Processes;
        public WindowRecord[] Windows;
    }
    public class Location {
        public string DesktopId;
        public bool OnCurrentDesktop;
    }
    public static class Native {
        delegate bool EnumWindowCallback(IntPtr window, IntPtr context);
        [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindowCallback callback, IntPtr context);
        [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
        [DllImport("user32.dll")] static extern bool IsWindow(IntPtr window);
        [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr window);
        [DllImport("user32.dll")] static extern IntPtr GetWindow(IntPtr window, uint command);
        [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")] static extern IntPtr GetWindowLongPtr(IntPtr window, int index);
        [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr OpenProcess(uint access, bool inherit, uint process);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool QueryFullProcessImageName(IntPtr process, uint flags, StringBuilder path, ref int size);
        [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
        public static ProcessRecord ReadProcess(int id) {
            IntPtr handle = OpenProcess(0x1000, false, (uint)id);
            if (handle == IntPtr.Zero) return null;
            try {
                var path = new StringBuilder(32768);
                int size = path.Capacity;
                if (!QueryFullProcessImageName(handle, 0, path, ref size)) return null;
                using (var process = Process.GetProcessById(id)) {
                    return new ProcessRecord { ProcessId = id, ExecutablePath = Path.GetFullPath(path.ToString()), StartedUtc = process.StartTime.ToUniversalTime() };
                }
            } catch (ArgumentException) { return null; }
              catch (InvalidOperationException) { return null; }
              catch (System.ComponentModel.Win32Exception) { return null; }
            finally { CloseHandle(handle); }
        }
        static WindowRecord Record(IntPtr window, ProcessRecord process) {
            return new WindowRecord { Handle = window.ToInt64(), ProcessId = process.ProcessId, ExecutablePath = process.ExecutablePath,
                StartedUtc = process.StartedUtc, Visible = IsWindowVisible(window), Owner = GetWindow(window, 4).ToInt64(),
                ToolWindow = (GetWindowLongPtr(window, -20).ToInt64() & 0x80) != 0 };
        }
        public static WindowRecord ReadWindow(long handle) {
            var window = new IntPtr(handle);
            uint id;
            if (!IsWindow(window) || GetWindowThreadProcessId(window, out id) == 0) return null;
            var process = ReadProcess((int)id);
            return process == null ? null : Record(window, process);
        }
        public static WindowSnapshot Capture(string[] executablePaths) {
            var paths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (string path in executablePaths) { paths.Add(Path.GetFullPath(path)); names.Add(Path.GetFileNameWithoutExtension(path)); }
            var processes = new Dictionary<int, ProcessRecord>();
            foreach (string name in names) {
                foreach (var process in Process.GetProcessesByName(name)) {
                    using (process) {
                        var record = ReadProcess(process.Id);
                        if (record != null && paths.Contains(record.ExecutablePath)) processes[record.ProcessId] = record;
                    }
                }
            }
            var windows = new List<WindowRecord>();
            EnumWindows(delegate(IntPtr window, IntPtr context) {
                uint id;
                GetWindowThreadProcessId(window, out id);
                ProcessRecord process;
                if (processes.TryGetValue((int)id, out process)) windows.Add(Record(window, process));
                return true;
            }, IntPtr.Zero);
            var processList = new List<ProcessRecord>(processes.Values);
            return new WindowSnapshot { Processes = processList.ToArray(), Windows = windows.ToArray() };
        }
        // ProcessStartInfo.Arguments follows the Windows argv quoting rules.
        public static string BuildArguments(string[] arguments) {
            var command = new StringBuilder();
            foreach (string argument in arguments) {
                if (argument == null || argument.IndexOf('\0') >= 0) throw new ArgumentException("Invalid argument.");
                if (command.Length > 0) command.Append(' ');
                command.Append('"');
                int slashes = 0;
                foreach (char value in argument) {
                    if (value == '\\') { slashes++; continue; }
                    if (value == '"') { command.Append('\\', slashes * 2 + 1); command.Append('"'); }
                    else { command.Append('\\', slashes); command.Append(value); }
                    slashes = 0;
                }
                command.Append('\\', slashes * 2); command.Append('"');
            }
            return command.ToString();
        }
    }
    [ComImport, Guid("6D5140C1-7436-11CE-8034-00AA006009FA"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IServiceProvider {
        [PreserveSig] int QueryService(ref Guid service, ref Guid iid, [MarshalAs(UnmanagedType.IUnknown)] out object result);
    }
    [ComImport, Guid("92CA9DCD-5622-4BBA-A805-5E9F541BD8C9"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IObjectArray {
        [PreserveSig] int GetCount(out uint count);
        [PreserveSig] int GetAt(uint index, ref Guid iid, [MarshalAs(UnmanagedType.Interface)] out object value);
    }
    [ComImport, Guid("FF72FFDD-BE7E-43FC-9C03-AD81681E88E4"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IVirtualDesktop {
        [PreserveSig] int IsViewVisible(IntPtr view, [MarshalAs(UnmanagedType.Bool)] out bool visible);
        [PreserveSig] int GetId(out Guid id);
    }
    [ComImport, Guid("F31574D6-B682-4CDC-BD56-1827860ABEC6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IVirtualDesktopManagerInternal {
        [PreserveSig] int GetCount(out uint count);
        [PreserveSig] int MoveViewToDesktop(IntPtr view, IVirtualDesktop desktop);
        [PreserveSig] int CanViewMoveDesktops(IntPtr view, [MarshalAs(UnmanagedType.Bool)] out bool allowed);
        [PreserveSig] int GetCurrentDesktop(out IVirtualDesktop desktop);
        [PreserveSig] int GetDesktops(out IObjectArray desktops);
        [PreserveSig] int GetAdjacentDesktop(IVirtualDesktop from, int direction, out IVirtualDesktop desktop);
        [PreserveSig] int SwitchDesktop(IVirtualDesktop desktop);
        [PreserveSig] int CreateDesktop(out IVirtualDesktop desktop);
    }
    [ComImport, Guid("1841C6D7-4F9D-42C0-AF41-8747538F10E5"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IApplicationViewCollection {
        [PreserveSig] int GetViews(out IObjectArray views);
        [PreserveSig] int GetViewsByZOrder(out IObjectArray views);
        [PreserveSig] int GetViewsByAppUserModelId([MarshalAs(UnmanagedType.LPWStr)] string id, out IObjectArray views);
        [PreserveSig] int GetViewForHwnd(IntPtr window, out IntPtr view);
    }
    public class DesktopInfo {
        public int Number;
        public string Id;
        public bool Current;
    }
    public class Destination {
        public string OriginalCurrentId;
        public DesktopInfo Target;
        public bool Created;
    }
    public class MoveResult {
        public long Window;
        public uint ProcessId;
        public string TargetId;
        public int TargetNumber;
        public string CurrentDesktopBefore;
        public string CurrentDesktopAfter;
    }
    public class Controller {
        readonly IServiceProvider shell;
        readonly IVirtualDesktopManagerInternal manager;
        readonly IPublicDesktopManager publicManager;
        static readonly Guid DesktopIid = new Guid("FF72FFDD-BE7E-43FC-9C03-AD81681E88E4");
        [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
        static void Check(int result) { Marshal.ThrowExceptionForHR(result); }
        public Controller() {
            shell = (IServiceProvider)Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("C2F03A33-21F5-47FA-B4BB-156362A2F239")));
            Guid service = new Guid("C5E0CDCA-7B6E-41B2-9FC4-D93975CC467B");
            Guid iid = new Guid("F31574D6-B682-4CDC-BD56-1827860ABEC6");
            object result;
            Check(shell.QueryService(ref service, ref iid, out result));
            manager = (IVirtualDesktopManagerInternal)result;
            publicManager = (IPublicDesktopManager)Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("AA509086-5CA9-4C25-8F95-589D3C07B48A")));
        }
        static Guid Id(IVirtualDesktop desktop) { Guid id; Check(desktop.GetId(out id)); return id; }
        Guid CurrentId() { IVirtualDesktop current; Check(manager.GetCurrentDesktop(out current)); return Id(current); }
        IVirtualDesktop At(IObjectArray desktops, uint index) {
            Guid iid = DesktopIid;
            object result;
            Check(desktops.GetAt(index, ref iid, out result));
            return (IVirtualDesktop)result;
        }
        public DesktopInfo[] Inventory() {
            Guid current = CurrentId();
            IObjectArray desktops;
            uint count, managerCount;
            Check(manager.GetDesktops(out desktops));
            Check(desktops.GetCount(out count));
            Check(manager.GetCount(out managerCount));
            if (count != managerCount || count == 0 || count > 64) throw new InvalidOperationException("Desktop inventory failed consistency checks.");
            var results = new List<DesktopInfo>();
            for (uint index = 0; index < count; index++) {
                Guid id = Id(At(desktops, index));
                results.Add(new DesktopInfo { Number = (int)index + 1, Id = id.ToString(), Current = id == current });
            }
            if (!results.Exists(d => d.Current)) throw new InvalidOperationException("Current desktop was not found.");
            return results.ToArray();
        }
        public Destination EnsureDestination(int desktopNumber) {
            var desktops = Inventory();
            string original = Array.Find(desktops, d => d.Current).Id;
            if (desktopNumber > 0) {
                var requested = Array.Find(desktops, d => d.Number == desktopNumber);
                if (requested == null) throw new ArgumentException("Requested desktop does not exist.");
                return new Destination { OriginalCurrentId = original, Target = requested, Created = false };
            }
            var other = Array.Find(desktops, d => !d.Current);
            if (other != null) return new Destination { OriginalCurrentId = original, Target = other, Created = false };
            IVirtualDesktop created;
            Check(manager.CreateDesktop(out created));
            string createdId = Id(created).ToString();
            var target = Array.Find(Inventory(), d => d.Id == createdId);
            if (target == null || CurrentId().ToString() != original) throw new InvalidOperationException("Destination creation verification failed.");
            return new Destination { OriginalCurrentId = original, Target = target, Created = true };
        }
        public Location Locate(long windowHandle) {
            Guid desktop;
            bool current;
            Check(publicManager.GetWindowDesktopId(new IntPtr(windowHandle), out desktop));
            Check(publicManager.IsWindowOnCurrentVirtualDesktop(new IntPtr(windowHandle), out current));
            return new Location { DesktopId = desktop.ToString(), OnCurrentDesktop = current };
        }
        public MoveResult Move(WindowRecord expected, string destinationId) {
            long windowHandle = expected.Handle;
            uint expectedProcess = (uint)expected.ProcessId;
            IntPtr window = new IntPtr(windowHandle);
            uint owner;
            if (GetWindowThreadProcessId(window, out owner) == 0 || owner != expectedProcess) throw new InvalidOperationException("Window owner changed; refusing move.");
            var actual = Native.ReadWindow(windowHandle);
            if (actual == null || actual.Key != expected.Key || !String.Equals(actual.ExecutablePath, expected.ExecutablePath, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Window identity changed; refusing move.");
            Guid targetId = Guid.Parse(destinationId);
            string currentBefore = CurrentId().ToString();
            var info = Array.Find(Inventory(), d => d.Id == targetId.ToString());
            if (info == null) throw new InvalidOperationException("Destination desktop is absent.");
            IObjectArray desktops;
            Check(manager.GetDesktops(out desktops));
            var destination = At(desktops, (uint)info.Number - 1);
            Guid service = new Guid("1841C6D7-4F9D-42C0-AF41-8747538F10E5");
            Guid iid = service;
            object collectionObject;
            Check(shell.QueryService(ref service, ref iid, out collectionObject));
            var collection = (IApplicationViewCollection)collectionObject;
            IntPtr view;
            Check(collection.GetViewForHwnd(window, out view));
            if (view == IntPtr.Zero) throw new InvalidOperationException("No application view for the game window.");
            try {
                bool allowed;
                Check(manager.CanViewMoveDesktops(view, out allowed));
                if (!allowed) throw new InvalidOperationException("Windows disallowed moving this view.");
                Check(manager.MoveViewToDesktop(view, destination));
            } finally { Marshal.Release(view); }
            return new MoveResult { Window = windowHandle, ProcessId = owner, TargetId = targetId.ToString(), TargetNumber = info.Number, CurrentDesktopBefore = currentBefore, CurrentDesktopAfter = CurrentId().ToString() };
        }
    }
}
