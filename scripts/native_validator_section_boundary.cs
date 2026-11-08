// UNINSTALLED fixed parent-section delivery body. No Main/default/tool route.
// Trusted pre-load policy, permanent approval and independent supervision MUST
// precede use. Never build/load checkout code elevated. Pins are NOT authority.
using System;
using System.Globalization;
using AiAgent.ValidatorGuardian;
namespace AiAgent.ValidatorDelivery {
    internal interface ISectionMemory {
        object NewSection(int bytes);
        void RequireHandle(object handle,bool readOnly,bool inheritable);
        object Map(object handle,int bytes,bool write);
        void Write(object view,byte[] bytes);
        byte[] Copy(object view,int bytes);
        object ReadOnlyDuplicate(object writer);
        void Unmap(object view);
        void Close(object handle);
    }
    internal sealed class SectionWindow : IGuardianClock {
        readonly object sync=new object();
        readonly IGuardianClock source;
        internal readonly double Deadline;
        internal readonly long ExpiresUnix;
        double last=Double.NegativeInfinity;
        internal SectionWindow(IGuardianClock time,double cap,long until) {
            if (time==null || Double.IsNaN(cap) || Double.IsInfinity(cap) || cap<=0 || until<1 || until>253402300799L)
                throw new GuardianRefused("section_window_plan");
            source=time; Deadline=cap; ExpiresUnix=until;
        }
        public double Seconds {
            get { lock (sync) {
                double now=source.Seconds;
                if (Double.IsNaN(now) || Double.IsInfinity(now) || now<0 || now>1000000000 || now<last)
                    throw new GuardianUnknown("section_clock_unknown");
                last=now; return now;
            } }
        }
        public long Unix { get { return source.Unix; } }
        internal void Require() {
            double now=Seconds; long wall=Unix;
            if (now>=Deadline || wall<1 || wall>=ExpiresUnix) throw new GuardianRefused("section_window");
        }
    }
    internal interface ISectionCounter { long Frequency(); long Read(); }
    internal sealed class SectionCounterFrame {
        internal readonly long Limit,Frequency;
        internal SectionCounterFrame(long limit,long rate) { Limit=limit; Frequency=rate; }
        internal static SectionCounterFrame Capture(SectionWindow window,ISectionCounter counter) {
            if (window==null || counter==null) throw new GuardianRefused("section_counter_plan");
            // EARLIER common counter, then local sample; setup already consumed
            // the core's real stopAt. No duration is renewed or reserve added back.
            long rate=counter.Frequency(),first=counter.Read();
            double now=window.Seconds; long wall=window.Unix;
            long second=counter.Read(),again=counter.Frequency();
            if (rate<1 || rate>1000000000L || again!=rate || first<1 || second<first || second-first>rate/4)
                throw new GuardianRefused("section_counter_sample");
            double remaining=Math.Min(window.Deadline-now,window.ExpiresUnix-wall);
            if (wall<1 || Double.IsNaN(remaining) || Double.IsInfinity(remaining) || remaining<=0 || remaining>900)
                throw new GuardianRefused("section_counter_window");
            try {
                long ticks=(long)Decimal.Floor((decimal)remaining*rate)-rate/1000-1;
                long limit=checked(first+ticks);
                if (ticks<1 || limit<=second) throw new GuardianRefused("section_counter_window");
                return new SectionCounterFrame(limit,rate);
            } catch (OverflowException) { throw new GuardianRefused("section_counter_window"); }
        }
    }
    internal static class SectionWorkerCommand {
        internal const string Mode="--provision-once-section-v1";
        internal const int MaxCommandChars=1024;
        static string N(long value) { return value.ToString(CultureInfo.InvariantCulture); }
        internal static string[] Arguments(GuardianRequest request,long handle,SectionCounterFrame frame) {
            if (request==null || handle<4 || handle%4!=0 || frame==null || frame.Limit<1 ||
                frame.Frequency<1 || frame.Frequency>1000000000L)
                throw new GuardianRefused("section_command_frame");
            return new string[] {Mode,N(handle),N(request.Bytes),request.Sha256,N(request.Plan.BudgetSeconds),
                N(request.Plan.ApprovedUntilUnix),N(frame.Limit),N(frame.Frequency)};
        }
        internal static string Command(GuardianRequest request,long handle,SectionCounterFrame frame) {
            string[] args=Arguments(request,handle,frame);
            string value="\""+request.Plan.Root+"\\"+ProvisionProcessGuardian.WorkerExe+"\" "+String.Join(" ",args);
            if (value.Length>=MaxCommandChars || value.IndexOf('\0')>=0) throw new GuardianRefused("section_command_bound");
            return value; // fixed EXE and decimal/hash metadata ONLY; never raw request argv
        }
    }
    internal sealed class ReadOnlyRequestSection {
        readonly object sync=new object();
        readonly ISectionMemory api;
        readonly GuardianRequest request;
        readonly SectionWindow window;
        object reader;
        internal ReadOnlyRequestSection(ISectionMemory memory,object read,GuardianRequest bound,SectionWindow time) {
            api=memory; reader=read; request=bound; window=time;
        }
        internal object ReadHandle {
            get { lock (sync) { if (reader==null) throw new GuardianRefused("section_closed"); return reader; } }
        }
        internal void Reverify() {
            lock (sync) {
                object read=ReadHandle,view=null;
                try {
                    window.Require(); api.RequireHandle(read,true,true); window.Require();
                    view=api.Map(read,(int)request.Bytes,false);
                    if (view==null || Object.Equals(view,read)) throw new GuardianUnknown("section_view_unknown");
                    window.Require();
                    if (!request.Matches(api.Copy(view,(int)request.Bytes))) throw new GuardianRefused("section_readback");
                    window.Require(); api.RequireHandle(read,true,true); window.Require();
                } finally {
                    object old=view; view=null;
                    if (old!=null && !Object.Equals(old,read)) {
                        try { api.Unmap(old); } catch { throw new GuardianUnknown("section_unmap_unknown"); }
                    }
                }
                window.Require();
            }
        }
        internal void Close() {
            lock (sync) {
                // Parent READ capability only. Safe to close even after uncertain
                // creation: an inherited child copy has its own reference. This
                // is NEVER release of held imports/executable targets or proof of
                // process absence. No finalizer, reset or native close retry.
                object old=reader; reader=null;
                if (old!=null) {
                    try { api.Close(old); } catch { throw new GuardianUnknown("section_close_unknown"); }
                }
            }
        }
    }
    internal sealed class SectionPublisher {
        readonly object sync=new object();
        readonly ISectionMemory api;
        readonly GuardianRequest request;
        readonly SectionWindow window;
        object writer,reader,view;
        bool used;
        internal SectionPublisher(ISectionMemory memory,GuardianRequest bound,SectionWindow time) {
            if (memory==null || bound==null || time==null) throw new GuardianRefused("section_plan");
            api=memory; request=bound; window=time;
        }
        object Own(object value) {
            if (value==null || Object.Equals(value,writer) || Object.Equals(value,reader) || Object.Equals(value,view))
                throw new GuardianUnknown("section_resource_unknown");
            return value;
        }
        void Unmap() {
            object old=view; view=null;
            if (old!=null) api.Unmap(old);
        }
        void CloseWriter() {
            object old=writer; writer=null;
            if (old!=null) api.Close(old);
        }
        void CloseAll() {
            bool unknown=false;
            try { Unmap(); } catch { unknown=true; }
            object old=reader; reader=null;
            try { if (old!=null) api.Close(old); } catch { unknown=true; }
            try { CloseWriter(); } catch { unknown=true; }
            if (unknown) throw new GuardianUnknown("section_close_unknown");
        }
        internal ReadOnlyRequestSection Publish() {
            lock (sync) {
                if (used) throw new GuardianRefused("section_one_shot"); used=true;
                try {
                    window.Require();
                    writer=Own(api.NewSection((int)request.Bytes));
                    api.RequireHandle(writer,false,false); window.Require();
                    view=Own(api.Map(writer,(int)request.Bytes,true));
                    window.Require(); api.Write(view,request.CopyRequest()); window.Require();
                    if (!request.Matches(api.Copy(view,(int)request.Bytes))) throw new GuardianRefused("section_writeback");
                    window.Require(); Unmap(); window.Require();
                    reader=Own(api.ReadOnlyDuplicate(writer));
                    api.RequireHandle(reader,true,true); window.Require();
                    // Remove ALL owned write capability BEFORE returning a read
                    // lease or building a process. Trusted parent must have made
                    // no other aliases, mappings or concurrent uncontrolled spawn.
                    CloseWriter(); window.Require();
                    var answer=new ReadOnlyRequestSection(api,reader,request,window);
                    answer.Reverify(); window.Require();
                    reader=null; return answer; // transfer only after checked readback/closure
                } finally { CloseAll(); }
            }
        }
    }
}
