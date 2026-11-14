// Fixed outer owner for the EXISTING approved-command channel. No installer,
// policy discovery, result writer, retry or general executable selector.
// Its own OS/CLR/module loading is an independently reviewed trust prerequisite.
using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Security.Principal;
using System.Text.RegularExpressions;

namespace AiAgent.ApprovedCommands {
internal static class ApprovedCommandBootstrap {
    static string Installation() {
        return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "AiAgentElevatedCommands");
    }
    static void Admission(string root) {
        if (IntPtr.Size!=8 || Path.GetDirectoryName(typeof(ApprovedCommandBootstrap).Assembly.Location)!=root)
            throw new Exception("Protected x64 bootstrap required");
        using (WindowsIdentity identity=WindowsIdentity.GetCurrent()) {
            if (!new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator))
                throw new Exception("Administrator consent required");
        }
    }
    static long Number(string text,long maximum) {
        long value;
        if (!Int64.TryParse(text,NumberStyles.None,CultureInfo.InvariantCulture,out value) || value<1 || value>maximum ||
            value.ToString(CultureInfo.InvariantCulture)!=text) throw new Exception("Invalid bootstrap frame");
        return value;
    }
    static void EnvironmentForWorker(string root,string system) {
        string[] keep=new string[]{"SystemRoot","WINDIR","SystemDrive","ProgramFiles","ProgramFiles(x86)","ProgramW6432",
            "CommonProgramFiles","CommonProgramFiles(x86)","CommonProgramW6432","USERNAME","USERDOMAIN",
            "USERPROFILE","HOMEDRIVE","HOMEPATH","LOCALAPPDATA","APPDATA","OS","PROCESSOR_ARCHITECTURE","NUMBER_OF_PROCESSORS"};
        var keys=new System.Collections.Generic.List<string>();
        foreach (string key in Environment.GetEnvironmentVariables().Keys) keys.Add(key);
        foreach (string key in keys) {
            bool found=false; foreach (string allowed in keep) if (String.Equals(allowed,key,StringComparison.OrdinalIgnoreCase)) found=true;
            if (!found) Environment.SetEnvironmentVariable(key,null);
        }
        Environment.SetEnvironmentVariable("PATH",system);
        Environment.SetEnvironmentVariable("ComSpec",Path.Combine(system,"cmd.exe"));
        Environment.SetEnvironmentVariable("PSModulePath",Path.Combine(system,@"WindowsPowerShell\v1.0\Modules"));
        Environment.SetEnvironmentVariable("TEMP",Path.Combine(root,"receipts"));
        Environment.SetEnvironmentVariable("TMP",Path.Combine(root,"receipts"));
    }
    public static int Main(string[] args) {
        // Start BEFORE admission, environment work or lease acquisition. The
        // child receives this same cap; no post-compilation timeout renewal.
        long first=Stopwatch.GetTimestamp(),rate=Stopwatch.Frequency;
        long wall=DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        try {
            if (args==null || args.Length!=8 || args[0]!="--approved-command-bootstrap-v1" ||
                !Regex.IsMatch(args[1],@"\A[0-9a-f]{32}\z") || !Regex.IsMatch(args[3],@"\A[0-9a-f]{64}\z")) return 2;
            long deadline=Number(args[2],253402300799L),seconds=Number(args[4],900),pid=Number(args[6],UInt32.MaxValue);
            Number(args[7],Int64.MaxValue);
            if (first<1 || rate<1 || rate>1000000000L) return 2;
            decimal available=Math.Min((decimal)seconds*1000,(decimal)deadline*1000-wall);
            if (available<=0 || (decimal)deadline*1000-wall>1800000) return 2;
            long limit=checked(first+(long)Decimal.Floor(available*rate/1000));
            string root=Installation(),system=Environment.GetFolderPath(Environment.SpecialFolder.System);
            Admission(root); EnvironmentForWorker(root,system);
            string exe=Path.Combine(system,@"WindowsPowerShell\v1.0\powershell.exe");
            string helper=Path.Combine(root,"helper.ps1");
            string command="-NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -File \""+helper+
                "\" -RequestId "+args[1]+" -DeadlineUnix "+args[2]+" -RequestSha256 "+args[3]+
                " -BootstrapSupervised 1 -BootstrapTimeout "+args[4];
            CommandWatchdog.Answer answer;
            using (var owner=CommandWatchdog.Prepare((uint)(seconds*1000),limit,rate,deadline,args[5],(uint)pid,args[7],args[1])) {
                answer=CommandWatchdog.RunPreparation(owner,exe,command,root);
            }
            // No disk I/O here: the helper's claim/result operations are ALL
            // inside this job. A protected receipt alone cannot prove our end.
            if (answer.Code!=0 || answer.Timeout || answer.Cancelled || answer.Truncated ||
                !answer.ProcessTreeObserved || !answer.LifetimeObserved || !answer.PreparationObserved ||
                answer.Stdout!="" || answer.Stderr!="") return 2;
            return 0;
        } catch { return 2; } // UNKNOWN; never effect verification or retry authority
    }
}
}
