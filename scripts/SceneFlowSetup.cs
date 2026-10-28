// Build with the Windows .NET Framework compiler. No global Python/Node installer.
using System;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Windows.Forms;

class SceneFlowSetup {
  static string root=AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
  static string uv=Path.Combine(root,"tools","uv","uv.exe");
  static bool headless=false;
  static string python=Path.Combine(root,".venv","Scripts","python.exe");
  static string At(params string[] parts) { var path=root;foreach(var part in parts)path=Path.Combine(path,part);return path; }
  static string Hash(string path) { using(var input=File.OpenRead(path))using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(input)).Replace("-","").ToLowerInvariant(); }
  static bool Valid(string path,long bytes,string hash) { return File.Exists(path)&&new FileInfo(path).Length==bytes&&Hash(path)==hash; }
  static string Fetch(string url,string name,long bytes,string hash) {
    var path=At("cache","bootstrap",name);Directory.CreateDirectory(Path.GetDirectoryName(path));
    if(Valid(path,bytes,hash))return path;
    Console.WriteLine("Downloading "+name+" into this Studio folder...");
    var part=path+".part";var request=(HttpWebRequest)WebRequest.Create(url);request.Timeout=120000;request.ReadWriteTimeout=120000;request.UserAgent="SceneFlow-Setup";
    using(var response=request.GetResponse())using(var input=response.GetResponseStream())using(var output=File.Create(part)) {
      var buffer=new byte[1024*1024];long count=0;int got;
      while((got=input.Read(buffer,0,buffer.Length))>0){count+=got;if(count>bytes)throw new Exception("A download exceeded its reviewed size. Setup stopped safely.");output.Write(buffer,0,got);}
    }
    if(!Valid(part,bytes,hash))throw new Exception("The download did not pass its checksum. Run setup again to retry.");
    if(File.Exists(path))File.Delete(path);File.Move(part,path);return path;
  }
  static void Extract(string archive,string destination) {
    Directory.CreateDirectory(destination);var prefix=Path.GetFullPath(destination)+Path.DirectorySeparatorChar;
    using(var zip=ZipFile.OpenRead(archive)){
      long total=0;if(zip.Entries.Count>20000)throw new Exception("Unexpected setup archive.");
      foreach(var entry in zip.Entries){total+=entry.Length;var path=Path.GetFullPath(Path.Combine(destination,entry.FullName));if(!path.StartsWith(prefix,StringComparison.OrdinalIgnoreCase)||entry.FullName.Contains(":")||((entry.ExternalAttributes>>16)&0xF000)==0xA000||total>1024L*1024*1024)throw new Exception("An unsafe setup archive was rejected.");}
      foreach(var entry in zip.Entries){var path=Path.GetFullPath(Path.Combine(destination,entry.FullName));if(entry.FullName.EndsWith("/")){Directory.CreateDirectory(path);continue;}Directory.CreateDirectory(Path.GetDirectoryName(path));entry.ExtractToFile(path,true);}
    }
  }
  static int Run(string exe,string arguments) {
    var info=new ProcessStartInfo(exe,arguments){WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true};
    var cache=At("cache");Directory.CreateDirectory(cache);Directory.CreateDirectory(At("temp"));
    foreach(var key in new[]{"TEMP","TMP"})info.EnvironmentVariables[key]=At("temp");
    info.EnvironmentVariables["UV_CACHE_DIR"]=At("cache","uv");info.EnvironmentVariables["UV_PYTHON_INSTALL_DIR"]=At("tools","python");info.EnvironmentVariables["UV_PYTHON_BIN_DIR"]=At("tools","python-bin");info.EnvironmentVariables["UV_PYTHON_INSTALL_REGISTRY"]="false";info.EnvironmentVariables["PYTHONIOENCODING"]="utf-8";info.EnvironmentVariables["PIP_CACHE_DIR"]=At("cache","pip");
    Directory.CreateDirectory(At("logs"));using(var log=new StreamWriter(At("logs","beginner-setup.log"),true))using(var process=new Process()){
      process.StartInfo=info;process.OutputDataReceived+=(s,e)=>{if(e.Data!=null)lock(log)log.WriteLine(e.Data);};process.ErrorDataReceived+=(s,e)=>{if(e.Data!=null)lock(log)log.WriteLine(e.Data);};process.Start();process.BeginOutputReadLine();process.BeginErrorReadLine();
      if(!process.WaitForExit(1200000)){process.Kill();throw new Exception("Setup reached its time limit. Run it again to reuse downloaded files.");}process.WaitForExit();return process.ExitCode;
    }
  }
  static bool MediaReady() {var path=At("tools","ffmpeg");return Directory.Exists(path)&&Directory.GetFiles(path,"ffmpeg.exe",SearchOption.AllDirectories).Length>0&&Directory.GetFiles(path,"ffprobe.exe",SearchOption.AllDirectories).Length>0;}
  [STAThread] static int Main(string[] args) {
    try {
      headless=Array.IndexOf(args,"--headless")>=0;
      ServicePointManager.SecurityProtocol=SecurityProtocolType.Tls12;
      if(!File.Exists(At("frontend","dist","index.html")))throw new Exception("This is a developer source download. Get the Windows app ZIP from the SceneFlow GitHub Releases page; it includes the finished interface.");
      bool programReady=File.Exists(python)&&Run(python,"-I -c \"import fastapi,uvicorn,PIL,psutil,httpx,websockets,multipart\"")==0;
      if(programReady&&MediaReady()){Console.WriteLine("Your Studio program and media tools are ready.");return 0;}
      if(new DriveInfo(Path.GetPathRoot(root)).AvailableFreeSpace<3L*1024*1024*1024)throw new Exception("Choose a Studio folder on a drive with at least 3 GB free, then open START_STUDIO again. Model files need additional space later.");
      if(Array.IndexOf(args,"--approved")<0&&MessageBox.Show("SceneFlow will add its private program and media tools here:\n\n"+root+"\n\nAllow up to 400 MB of downloads and 3 GB of working space. Creation models are chosen separately inside the app. Your existing ComfyUI, Python and drivers are preserved.\n\nSet up now?","Set up SceneFlow",MessageBoxButtons.YesNo,MessageBoxIcon.Information)!=DialogResult.Yes)return 2;
      if(!programReady){
        var archive=Fetch("https://github.com/astral-sh/uv/releases/download/0.10.0/uv-x86_64-pc-windows-msvc.zip","uv-0.10.0.zip",21758991,"4037b444541f695cd2eb93188a9346de3e334af562381411deade0a31c7bf898");Extract(archive,At("tools","uv"));
        if(!File.Exists(uv)){var found=Directory.GetFiles(At("tools","uv"),"uv.exe",SearchOption.AllDirectories);if(found.Length!=1)throw new Exception("Setup helper missing.");File.Copy(found[0],uv,true);}
        Console.WriteLine("Adding private Python. This does not change your system Python.");
        if(Run(uv,"-qq python install 3.12.12 --no-bin --no-registry --install-dir \""+At("tools","python")+"\"")!=0)throw new Exception("Private Python could not finish. See logs/beginner-setup.log, then retry.");
        var basePython=At("tools","python","cpython-3.12.12-windows-x86_64-none","python.exe");
        if(!File.Exists(python)&&Run(uv,"-qq venv --python \""+basePython+"\" \""+At(".venv")+"\"")!=0)throw new Exception("The private program folder could not be created.");
        Console.WriteLine("Installing verified Studio packages...");
        if(Run(uv,"-qq pip sync --python \""+python+"\" --require-hashes --link-mode hardlink \""+At("backend","bootstrap-lock.txt")+"\"")!=0)throw new Exception("Studio packages could not finish. Retry using the saved cache; details are in logs/beginner-setup.log.");
        if(Run(python,"-I -c \"import fastapi,uvicorn,PIL,psutil,httpx,websockets,multipart\"")!=0)throw new Exception("Studio program check failed. See logs/beginner-setup.log.");
      }
      if(!MediaReady()){
        var archive=Fetch("https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip","ffmpeg-9.0.2.zip",114768076,"60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba");Extract(archive,At("tools","ffmpeg","portable"));
      }
      if(!MediaReady())throw new Exception("Media tools could not be verified.");
      Console.WriteLine("Setup complete. Your Studio is ready to open.");return 0;
    }catch(Exception error){Console.WriteLine(error.Message);if(!headless)MessageBox.Show(error.Message,"SceneFlow setup needs attention",MessageBoxButtons.OK,MessageBoxIcon.Warning);return 1;}
  }
}
