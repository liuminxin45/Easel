"""Preserve owner-only file ACLs before writing secret state atomically."""
import ctypes, json, os, pathlib, stat, tempfile


def security(path):
    if os.name!='nt':return ('mode',stat.S_IMODE(os.stat(path).st_mode))
    adv=ctypes.WinDLL('advapi32',use_last_error=True)
    size=ctypes.c_ulong()
    adv.GetFileSecurityW(str(path),4,None,0,ctypes.byref(size))
    buf=ctypes.create_string_buffer(size.value)
    if not adv.GetFileSecurityW(str(path),4,buf,size.value,ctypes.byref(size)):raise OSError('Cannot read credential ACL')
    control=ctypes.c_ushort();revision=ctypes.c_ulong()
    if not adv.GetSecurityDescriptorControl(buf,ctypes.byref(control),ctypes.byref(revision)):raise OSError('Cannot read ACL control')
    return ('dacl',buf.raw,bool(control.value & 0x1000))


def apply_security(path,acl):
    if acl[0]=='mode':os.chmod(path,acl[1]);return
    adv=ctypes.WinDLL('advapi32',use_last_error=True)
    buf=ctypes.create_string_buffer(acl[1])
    flags=4 | (0x80000000 if acl[2] else 0x20000000)
    if not adv.SetFileSecurityW(str(path),ctypes.c_ulong(flags),buf):raise OSError('Cannot preserve credential ACL')


def atomic(path,text,acl):
    path=pathlib.Path(path)
    fd,name=tempfile.mkstemp(prefix='.auth-',dir=path.parent)
    try:
        # Set exact original DACL before any sensitive bytes are written.
        apply_security(name,acl)
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
            fd=None;f.write(text);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if fd is not None:os.close(fd)
        try:os.unlink(name)
        except FileNotFoundError:pass

