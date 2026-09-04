Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, int data, UIntPtr extra);
}
"@
[W]::SetProcessDPIAware()
[W]::SetCursorPos(1734, 855)
Start-Sleep -Milliseconds 200
[W]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
[W]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 500
[W]::mouse_event(0x0800, 0, 0, -360, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 1500
