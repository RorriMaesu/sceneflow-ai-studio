"""Native Windows folder picker, without Tk or an extra GUI dependency."""
def pick_folder():
    import os,threading
    if os.name!='nt':raise ValueError('Choose recommended folders on this system.')
    result={}
    def show():
        import ctypes,uuid
        from ctypes import wintypes
        ole=ctypes.OleDLL('ole32')
        class GUID(ctypes.Structure):
            _fields_=[('data',ctypes.c_ubyte*16)]
        def guid(value):return GUID((ctypes.c_ubyte*16).from_buffer_copy(uuid.UUID(value).bytes_le))
        def method(pointer,index,restype,*arguments):
            table=ctypes.cast(pointer,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            return ctypes.WINFUNCTYPE(restype,ctypes.c_void_p,*arguments)(table[index])
        def checked(code):
            if code<0:raise OSError('Windows folder selection failed (0x%08X).'%(code&0xffffffff))
        dialog=ctypes.c_void_p();item=ctypes.c_void_p();value=ctypes.c_void_p();initialized=False
        try:
            ole.CoInitializeEx.argtypes=[ctypes.c_void_p,wintypes.DWORD];ole.CoInitializeEx.restype=ctypes.c_long
            checked(ole.CoInitializeEx(None,2));initialized=True
            ole.CoCreateInstance.argtypes=[ctypes.POINTER(GUID),ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(GUID),ctypes.POINTER(ctypes.c_void_p)];ole.CoCreateInstance.restype=ctypes.c_long
            checked(ole.CoCreateInstance(ctypes.byref(guid('dc1c5a9c-e88a-4dde-a5a1-60f82a20aef7')),None,1,ctypes.byref(guid('d57c7288-d4ad-4768-be02-9d969532d960')),ctypes.byref(dialog)))
            checked(method(dialog,9,ctypes.c_long,wintypes.DWORD)(dialog,0x20|0x40|0x800|0x8|0x2000000))
            checked(method(dialog,17,ctypes.c_long,ctypes.c_wchar_p)(dialog,'Choose a SceneFlow library folder'))
            code=method(dialog,3,ctypes.c_long,wintypes.HWND)(dialog,None)
            if code&0xffffffff==0x800704c7:result['path']=None;return
            checked(code)
            checked(method(dialog,20,ctypes.c_long,ctypes.POINTER(ctypes.c_void_p))(dialog,ctypes.byref(item)))
            checked(method(item,5,ctypes.c_long,ctypes.c_uint,ctypes.POINTER(ctypes.c_void_p))(item,0x80058000,ctypes.byref(value)))
            result['path']=ctypes.wstring_at(value)
        except Exception as error:result['error']=error
        finally:
            if value:
                ole.CoTaskMemFree.argtypes=[ctypes.c_void_p];ole.CoTaskMemFree(value)
            if item:method(item,2,ctypes.c_ulong)(item)
            if dialog:method(dialog,2,ctypes.c_ulong)(dialog)
            if initialized:ole.CoUninitialize()
    thread=threading.Thread(target=show,name='SceneFlow folder chooser');thread.start();thread.join()
    if 'error' in result:raise ValueError('The Windows folder picker could not open. Use recommended folders, then try again.') from result['error']
    return result.get('path')
