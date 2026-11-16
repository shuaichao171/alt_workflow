// Windows Core Audio session controls. No endpoint/master-volume writes.
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace DsTestAudio
{
    [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
    class DeviceEnumeratorClass { }

    [ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IDeviceEnumerator
    {
        [PreserveSig] int EnumAudioEndpoints(int flow, uint mask, out IDeviceCollection devices);
    }
    [ComImport, Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IDeviceCollection
    {
        [PreserveSig] int GetCount(out uint count);
        [PreserveSig] int Item(uint index, out IDevice device);
    }
    [ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IDevice
    {
        [PreserveSig] int Activate(ref Guid iid, uint context, IntPtr parameters, [MarshalAs(UnmanagedType.IUnknown)] out object result);
        [PreserveSig] int OpenPropertyStore(uint access, out IntPtr store);
        [PreserveSig] int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
    }
    [ComImport, Guid("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface ISessionManager
    {
        [PreserveSig] int GetAudioSessionControl(ref Guid session, uint flags, out IntPtr control);
        [PreserveSig] int GetSimpleAudioVolume(ref Guid session, uint flags, out IntPtr volume);
        [PreserveSig] int GetSessionEnumerator(out ISessionEnumerator sessions);
    }
    [ComImport, Guid("E2F5BB11-0570-40CA-ACDD-3AA01277DEE8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface ISessionEnumerator
    {
        [PreserveSig] int GetCount(out int count);
        [PreserveSig] int GetSession(int index, [MarshalAs(UnmanagedType.IUnknown)] out object control);
    }
    [ComImport, Guid("BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface ISessionControl
    {
        [PreserveSig] int GetState(out int state);
        [PreserveSig] int GetDisplayName([MarshalAs(UnmanagedType.LPWStr)] out string name);
        [PreserveSig] int SetDisplayName([MarshalAs(UnmanagedType.LPWStr)] string name, ref Guid context);
        [PreserveSig] int GetIconPath([MarshalAs(UnmanagedType.LPWStr)] out string path);
        [PreserveSig] int SetIconPath([MarshalAs(UnmanagedType.LPWStr)] string path, ref Guid context);
        [PreserveSig] int GetGroupingParam(out Guid grouping);
        [PreserveSig] int SetGroupingParam(ref Guid grouping, ref Guid context);
        [PreserveSig] int RegisterAudioSessionNotification(IntPtr callback);
        [PreserveSig] int UnregisterAudioSessionNotification(IntPtr callback);
        [PreserveSig] int GetSessionIdentifier([MarshalAs(UnmanagedType.LPWStr)] out string identifier);
        [PreserveSig] int GetSessionInstanceIdentifier([MarshalAs(UnmanagedType.LPWStr)] out string identifier);
        [PreserveSig] int GetProcessId(out uint processId);
    }
    [ComImport, Guid("87CE5498-68D6-44E5-9215-6DA47EF883D8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface ISessionVolume
    {
        [PreserveSig] int SetMasterVolume(float level, ref Guid context);
        [PreserveSig] int GetMasterVolume(out float level);
        [PreserveSig] int SetMute([MarshalAs(UnmanagedType.Bool)] bool muted, ref Guid context);
        [PreserveSig] int GetMute([MarshalAs(UnmanagedType.Bool)] out bool muted);
    }

    public class Session
    {
        public string EndpointId { get; set; }
        public string InstanceId { get; set; }
        public uint ProcessId { get; set; }
        public int State { get; set; }
        public float Volume { get; set; }
        public bool Muted { get; set; }
    }

    public static class CoreAudio
    {
        static void Check(int hr) { Marshal.ThrowExceptionForHR(hr); }
        static void Release(object value)
        {
            if (value != null && Marshal.IsComObject(value)) Marshal.ReleaseComObject(value);
        }
        static void Visit(Action<Session, ISessionVolume> action)
        {
            var enumerator = (IDeviceEnumerator)new DeviceEnumeratorClass();
            IDeviceCollection devices = null;
            try
            {
                // Include non-default active playback devices too.
                Check(enumerator.EnumAudioEndpoints(0, 1, out devices));
                uint count; Check(devices.GetCount(out count));
                for (uint deviceIndex = 0; deviceIndex < count; deviceIndex++)
                {
                    IDevice device = null; object managerObject = null; ISessionEnumerator sessions = null;
                    try
                    {
                        Check(devices.Item(deviceIndex, out device));
                        string endpointId; Check(device.GetId(out endpointId));
                        Guid iid = typeof(ISessionManager).GUID;
                        Check(device.Activate(ref iid, 23, IntPtr.Zero, out managerObject));
                        Check(((ISessionManager)managerObject).GetSessionEnumerator(out sessions));
                        int sessionCount; Check(sessions.GetCount(out sessionCount));
                        for (int index = 0; index < sessionCount; index++)
                        {
                            object controlObject = null;
                            try
                            {
                                Check(sessions.GetSession(index, out controlObject));
                                var control = (ISessionControl)controlObject;
                                uint processId;
                                // Non-S_OK can indicate a session spanning multiple processes.
                                int processResult = control.GetProcessId(out processId);
                                Check(processResult);
                                if (processResult != 0 || processId == 0) continue;
                                int state; string instanceId;
                                Check(control.GetState(out state));
                                Check(control.GetSessionInstanceIdentifier(out instanceId));
                                var volume = (ISessionVolume)controlObject;
                                float level; bool muted;
                                Check(volume.GetMasterVolume(out level)); Check(volume.GetMute(out muted));
                                action(new Session { EndpointId = endpointId, InstanceId = instanceId,
                                    ProcessId = processId, State = state, Volume = level, Muted = muted }, volume);
                            }
                            finally { Release(controlObject); }
                        }
                    }
                    finally { Release(sessions); Release(managerObject); Release(device); }
                }
            }
            finally { Release(devices); Release(enumerator); }
        }

        public static Session[] Snapshot()
        {
            var rows = new List<Session>();
            Visit((row, volume) => rows.Add(row));
            return rows.ToArray();
        }

        public static bool SetMute(string endpointId, string instanceId, uint processId, bool muted)
        {
            bool confirmed = false;
            Visit((row, volume) =>
            {
                if (row.EndpointId != endpointId || row.InstanceId != instanceId || row.ProcessId != processId) return;
                Guid context = Guid.Empty;
                Check(volume.SetMute(muted, ref context));
                bool actual; Check(volume.GetMute(out actual));
                confirmed = actual == muted;
            });
            return confirmed;
        }
    }
}
