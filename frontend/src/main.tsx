import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  Activity,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  AudioLines,
  Check,
  ChevronDown,
  ChevronRight,
  Clapperboard,
  Clock,
  Command,
  Copy,
  Download,
  Edit3,
  ExternalLink,
  Eye,
  Film,
  Folder,
  Grid2X2,
  Image as ImageIcon,
  Layers,
  Link2,
  LoaderCircle,
  Lock,
  Menu,
  MessageCircle,
  Monitor,
  MoreHorizontal,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Save,
  Search,
  Settings as SettingsIcon,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Upload,
  Video,
  Volume2,
  WandSparkles,
  X,
  Zap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { z } from "zod";
import { initialPairCode, request, upload, useConnection } from "./api";
import type {
  Asset,
  Bootstrap,
  Job,
  Mode,
  Project,
  Scene,
  Workflow,
} from "./types";
import "./style.css";
import { ProductionSettings } from "./production-settings";
import { TimelineEditor } from "./timeline-editor";
import { BackupPanel, WorkflowImporter, SceneHistory } from "./tools-panels";
import { AssetQuality } from "./quality-panel";
import {
  VisualBible,
  CorrectionCanvas,
  CandidateReview,
} from "./continuity-panel";

const client = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});
const NAV: [string, LucideIcon, string][] = [
  ["Overview", Grid2X2, "workspace"],
  ["Storyboard", Layers, "workspace"],
  ["AI Director", Sparkles, "workspace"],
  ["Image Studio", ImageIcon, "production"],
  ["Video Studio", Video, "production"],
  ["Generation Queue", Activity, "production"],
  ["Timeline", Film, "production"],
  ["Exports", Download, "production"],
  ["Model Library", Clapperboard, "studio"],
  ["Settings", SettingsIcon, "studio"],
];
const MODES: { id: Mode; name: string; description: string }[] = [
  {
    id: "automatic",
    name: "Autopilot",
    description: "Let the studio produce your story.",
  },
  {
    id: "hybrid",
    name: "Assisted",
    description: "Keep creating while the studio works.",
  },
  { id: "manual", name: "Manual", description: "Direct every stage yourself." },
];
const fmt = (n: number) => (n ? `${(n / 1073741824).toFixed(1)} GB` : "—");
const short = (s: string) =>
  s
    .replaceAll("_", " ")
    .replace("image to video", "Video")
    .replace("text to image", "Still");
const phase = import.meta.env.VITE_PHASE || "Phase 1 · Foundation";
const featurePhase = Number(import.meta.env.VITE_FEATURE_PHASE || 1);
function Button({
  children,
  onClick,
  primary = false,
  disabled = false,
  title = "",
  className = "",
  type = "button",
  ...rest
}: {
  children: React.ReactNode;
  onClick?: () => void;
  primary?: boolean;
  disabled?: boolean;
  title?: string;
  className?: string;
  type?: "submit" | "button";
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...rest}
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`${primary ? "button primary" : "button"} ${className}`}
    >
      {children}
    </button>
  );
}
function Badge({
  children,
  tone = "",
}: {
  children: React.ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
function Empty({
  icon: Icon = Clapperboard,
  title,
  description,
  action,
}: {
  icon?: LucideIcon;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-symbol">
        <Icon size={28} />
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}

function Media({
  asset,
  className = "",
  controls = false,
}: {
  asset?: Asset;
  className?: string;
  controls?: boolean;
}) {
  const playback = useRef({ time: 0, playing: false });
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    playback.current = { time: 0, playing: false };
    setFailed(false);
  }, [asset?.id]);
  const mediaEvents = {
    onTimeUpdate: (e: React.SyntheticEvent<HTMLMediaElement>) => {
      playback.current.time = e.currentTarget.currentTime;
    },
    onPlay: () => {
      playback.current.playing = true;
    },
    onPause: (e: React.SyntheticEvent<HTMLMediaElement>) => {
      if (e.currentTarget.readyState > 1) playback.current.playing = false;
    },
    onLoadedMetadata: (e: React.SyntheticEvent<HTMLMediaElement>) => {
      const element = e.currentTarget;
      if (playback.current.time > 0 && Number.isFinite(element.duration))
        element.currentTime = Math.min(
          playback.current.time,
          Math.max(0, element.duration - 0.05),
        );
      if (playback.current.playing) element.play().catch(() => {});
      setFailed(false);
    },
    onError: () => setFailed(true),
  };
  const { data, refetch } = useQuery({
    queryKey: ["media", asset?.id],
    queryFn: () =>
      request<{ url: string }>(`/api/assets/${asset!.id}/ticket`, {}),
    enabled: !!asset,
    staleTime: 25 * 60 * 1000,
    refetchInterval: 25 * 60 * 1000,
  });
  if (!asset || !data)
    return (
      <div className={`media-placeholder ${className}`}>
        <ImageIcon size={24} />
      </div>
    );
  const source =
    useConnection.getState().url +
    data.url +
    (asset.kind === "image" && !controls ? "&thumbnail=true" : "");
  if (failed)
    return (
      <div className="media-placeholder">
        <p>Preview unavailable. Restore missing media or refresh its access.</p>
        <button
          className="button"
          onClick={() => {
            void refetch().then((result) => {
              if (result.data) setFailed(false);
            });
          }}
        >
          Refresh preview
        </button>
      </div>
    );
  return asset.kind === "video" || asset.kind === "export" ? (
    <video
      {...mediaEvents}
      className={className}
      src={source}
      controls={controls}
      muted={!controls}
      playsInline
      preload="metadata"
    />
  ) : asset.kind === "audio" ? (
    <audio {...mediaEvents} src={source} controls />
  ) : (
    <img className={className} src={source} alt="Scene asset" />
  );
}

function Studio() {
  const cache = useQueryClient();
  const connection = useConnection();
  const reduced = useReducedMotion();
  const [page, setPage] = useState("Overview");
  const [active, setActive] = useState(
    localStorage.getItem("sceneflow.project") || "",
  );
  const [selected, setSelected] = useState("");
  const [pairOpen, setPairOpen] = useState(!!initialPairCode);
  const [newOpen, setNewOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [toast, setToast] = useState("");
  const [busy, setBusy] = useState(false);
  const [sidebar, setSidebar] = useState(false);
  const boot = useQuery<Bootstrap>({
    queryKey: ["bootstrap", connection.token],
    queryFn: () => request("/api/bootstrap"),
    enabled: !!connection.token,
    refetchInterval: 7000,
  });
  const projectQuery = useQuery<Project>({
    queryKey: ["project", active, connection.token],
    queryFn: () => request("/api/projects/" + active),
    enabled: !!active && !!connection.token,
    refetchInterval: 5000,
  });
  const models = useQuery<Workflow[]>({
    queryKey: ["models", connection.token],
    queryFn: () => request("/api/workflows"),
    enabled: !!connection.token && featurePhase >= 2,
    staleTime: 10000,
  });
  const project = projectQuery.data;
  const data = boot.data;
  const scene = project?.scenes.find((s) => s.id === selected);
  const jobs = data?.jobs || [];
  const activeJobs = jobs.filter((j) =>
    ["running", "submitted", "reconciling"].includes(j.status),
  );
  const pending = jobs.filter((j) =>
    ["queued", "waiting", "awaiting_review"].includes(j.status),
  );
  const notify = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 5500);
  };
  const refresh = () => {
    cache.invalidateQueries({ queryKey: ["bootstrap"] });
    cache.invalidateQueries({ queryKey: ["project"] });
    cache.invalidateQueries({ queryKey: ["models"] });
  };
  async function act(fn: () => Promise<any>, success = "Saved") {
    setBusy(true);
    try {
      const value = await fn();
      refresh();
      if (success) notify(success);
      return value;
    } catch (e) {
      notify((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const choose = (id: string) => {
    setActive(id);
    localStorage.setItem("sceneflow.project", id);
    setSelected("");
    setPage("Storyboard");
  };
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "k") {
        event.preventDefault();
        setSearchOpen((v) => !v);
      }
      if (event.key === "Escape") {
        setPairOpen(false);
        setNewOpen(false);
        setSearchOpen(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
  useEffect(() => {
    if (!pairOpen && !newOpen && !searchOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
    if (!dialog) return;
    dialog.querySelector<HTMLElement>("input,textarea,button")?.focus();
    const trap = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const items = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          "button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href]",
        ),
      ).filter((el) => el.getClientRects().length);
      if (!items.length) return;
      if (e.shiftKey && document.activeElement === items[0]) {
        e.preventDefault();
        items[items.length - 1].focus();
      } else if (
        !e.shiftKey &&
        document.activeElement === items[items.length - 1]
      ) {
        e.preventDefault();
        items[0].focus();
      }
    };
    document.addEventListener("keydown", trap);
    return () => {
      document.removeEventListener("keydown", trap);
      if (previous?.isConnected) previous.focus();
    };
  }, [pairOpen, newOpen, searchOpen]);
  useEffect(() => {
    if (!connection.token) return;
    let socket: WebSocket | undefined;
    let stopped = false;
    let timer: number;
    const open = async () => {
      try {
        const { ticket } = await request("/api/events/ticket", {});
        if (stopped) return;
        socket = new WebSocket(
          connection.url.replace("http:", "ws:") +
            "/ws?ticket=" +
            encodeURIComponent(ticket),
        );
        socket.onmessage = (event) => {
          const value = JSON.parse(event.data);
          if (value.kind !== "heartbeat") refresh();
        };
        socket.onclose = () => {
          if (!stopped) timer = window.setTimeout(open, 4000);
        };
      } catch {
        if (!stopped) timer = window.setTimeout(open, 8000);
      }
    };
    open();
    return () => {
      stopped = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, [connection.token, connection.url]);
  async function newProject(title: string, brief: string, example = false) {
    const created = await act(async () => {
      const p = await request<Project>("/api/projects", {
        title,
        brief,
        mode: "hybrid",
      });
      if (example) {
        for (const [name, description] of EXAMPLE) {
          await request(`/api/projects/${p.id}/scenes`, {
            title: name,
            body: {
              summary: description,
              image_prompt: `A polished two-dimensional cartoon Halloween starting frame. ${description}. Dark theatrical background, clean bold outlines, expressive composition, space around the character. No text.`,
              video_prompt: `Preserve the exact starting artwork and character design. ${description}. Subtle breathing, one clear readable motion, candlelight flicker. Locked camera, no cuts.`,
              duration: 5,
            },
          });
        }
      }
      return p;
    }, "Project created");
    if (created) {
      choose(created.id);
      setNewOpen(false);
    }
  }
  async function modeChange(mode: Mode) {
    if (project)
      await act(
        () =>
          request(
            "/api/projects/" + project.id,
            {
              revision: project.revision,
              mode,
              settings: mode === "manual" ? { paused: true } : {},
            },
            "PATCH",
          ),
        mode === "manual"
          ? "Manual mode: active work can finish; new automatic jobs will wait."
          : "Production mode updated. Completed assets are preserved.",
      );
  }
  async function produce(scope: string) {
    if (!project) return;
    if (scope === "all" && !project.scenes.length) {
      if (!project.settings.llm || project.mode === "manual") {
        setPage("AI Director");
        notify(
          "Add scenes manually, or choose a local planning model to develop the brief.",
        );
        return;
      }
      await act(
        () =>
          request(`/api/projects/${project.id}/plan`, {
            model: project.settings.llm,
            scene_count: project.settings.scene_count || 4,
            auto_apply: project.mode === "automatic",
            auto_continue: project.mode === "automatic",
          }),
        "Planning queued. Hybrid mode presents a proposal for review.",
      );
      return;
    }
    await act(
      () =>
        request(`/api/projects/${project.id}/produce`, {
          scope,
          scene_id: selected || null,
        }),
      scope === "all"
        ? "Production planned from your existing valid assets."
        : "Jobs added to the production queue.",
    );
  }
  const go = (next: string) => {
    setPage(next);
    setSidebar(false);
  };
  return (
    <div className="app-shell">
      <aside className={`sidebar ${sidebar ? "open" : ""}`}>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            go("Overview");
          }}
        >
          <span className="brand-mark">
            <Clapperboard size={22} />
          </span>
          <span>
            SceneFlow<span className="brand-sub">AI STUDIO</span>
          </span>
        </a>
        <div className="workspace-label">
          PERSONAL WORKSPACE <ChevronDown size={13} />
        </div>
        <nav>
          {["workspace", "production", "studio"].map((group) => (
            <React.Fragment key={group}>
              <div className="nav-label">{group}</div>
              {NAV.filter((n) => n[2] === group).map(([label, Icon]) => (
                <button
                  key={label}
                  onClick={() => go(label)}
                  className={`nav-item ${page === label ? "active" : ""}`}
                >
                  <Icon size={18} />
                  <span>{label}</span>
                  {label === "Generation Queue" && pending.length > 0 && (
                    <small>{pending.length}</small>
                  )}
                </button>
              ))}
            </React.Fragment>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-card">
            <ShieldCheck size={18} />
            <div>
              <strong>Made here. Stays here.</strong>
              <span>Your studio runs on your PC.</span>
            </div>
          </div>
          <button className="agent-button" onClick={() => setPairOpen(true)}>
            <span className={`status-dot ${data ? "online" : ""}`} />
            <span>
              {data ? "Studio Agent connected" : "Connect Studio Agent"}
            </span>
            <Link2 size={14} />
          </button>
          <span className="release-label">{phase}</span>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="icon-button mobile-menu"
              onClick={() => setSidebar(!sidebar)}
              aria-label="Open navigation"
            >
              <Menu size={20} />
            </button>
            <span>Workspace</span>
            <ChevronRight size={14} />
            <strong>{page}</strong>
          </div>
          <div className="top-actions">
            <button
              className="search-button"
              onClick={() => setSearchOpen(true)}
            >
              <Search size={15} />
              <span>Find your next frame</span>
              <kbd>⌘ K</kbd>
            </button>
            <span className="local-tag">
              <Monitor size={13} /> LOCAL FIRST
            </span>
            <button
              className="avatar"
              onClick={() => go("Settings")}
              aria-label="Studio settings"
            >
              SF
            </button>
          </div>
        </header>
        <main>
          <AnimatePresence mode="wait">
            <motion.div
              key={page + (!project ? "" : active)}
              initial={reduced ? false : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.16 }}
            >
              {(!connection.token || boot.isError) && (
                <div className="connection-banner">
                  <Link2 size={17} />
                  <span>
                    {boot.isError
                      ? "The local agent is unavailable. Your saved work stays on your PC."
                      : "Connect your local Studio Agent to create and manage productions."}
                  </span>
                  <button onClick={() => setPairOpen(true)}>
                    Connect <ArrowRight size={14} />
                  </button>
                </div>
              )}
              {page === "Overview" ? (
                <>
                  <section className="hero">
                    <div className="hero-copy">
                      <span className="eyebrow">
                        <span /> YOUR IDEAS. IN MOTION.
                      </span>
                      <h1>
                        A little imagination.
                        <br />
                        <em>Endless possibilities.</em>
                      </h1>
                      <p>
                        Turn a spark of an idea into something worth watching.
                        <br />
                        Plan, create, and direct — all in your own studio.
                      </p>
                      <div className="hero-actions">
                        <Button
                          primary
                          onClick={() =>
                            connection.token
                              ? setNewOpen(true)
                              : setPairOpen(true)
                          }
                        >
                          <Plus size={17} />
                          Create a project
                        </Button>
                        <Button
                          onClick={() => {
                            if (project) go("AI Director");
                            else
                              connection.token
                                ? setNewOpen(true)
                                : setPairOpen(true);
                          }}
                        >
                          <Sparkles size={16} />
                          Create with AI
                        </Button>
                      </div>
                    </div>
                    <div className="hero-art" aria-hidden="true">
                      <div className="orbit orbit-one" />
                      <div className="orbit orbit-two" />
                      <div className="orbit orbit-three" />
                      <div className="art-frame frame-back">
                        <div className="mountain mountain-back" />
                        <div className="planet" />
                        <span className="frame-dot" />
                      </div>
                      <div className="art-frame frame-front">
                        <div className="cinema-sun" />
                        <div className="mountain" />
                        <div className="mountain two" />
                        <div className="frame-grain" />
                        <div className="art-caption">
                          <span>FROM IDEA TO FINAL CUT</span>
                          <Play size={15} />
                        </div>
                      </div>
                      <div className="art-spark">
                        <Sparkles size={24} />
                      </div>
                      <div className="art-chip">
                        <span className="status-dot online" /> Powered by your
                        imagination
                      </div>
                    </div>
                  </section>
                  <section className="section">
                    <div className="section-heading">
                      <div>
                        <h2>
                          Your productions{" "}
                          <span>{data?.projects.length || 0}</span>
                        </h2>
                        <p>Every great story starts somewhere.</p>
                      </div>
                      <Button
                        title="New project"
                        aria-label="New project"
                        onClick={() =>
                          connection.token
                            ? setNewOpen(true)
                            : setPairOpen(true)
                        }
                      >
                        <Plus size={16} />
                        New project
                      </Button>
                    </div>
                    {data?.projects.length ? (
                      <div className="project-grid">
                        {data.projects.map((p, index) => (
                          <button
                            key={p.id}
                            className="project-card"
                            onClick={() => choose(p.id)}
                          >
                            <div className={`project-cover cover-${index % 4}`}>
                              {data.assets.find(
                                (a) =>
                                  a.project_id === p.id && a.kind === "image",
                              ) ? (
                                <Media
                                  asset={data.assets.find(
                                    (a) =>
                                      a.project_id === p.id &&
                                      a.kind === "image",
                                  )}
                                />
                              ) : (
                                <>
                                  <div className="cover-lines" />
                                  <Clapperboard size={38} />
                                  <span className="cover-word">
                                    {p.title.split(" ").slice(0, 2).join(" ")}
                                  </span>
                                </>
                              )}
                              <Badge>
                                {MODES.find((m) => m.id === p.mode)?.name}
                              </Badge>
                            </div>
                            <div className="project-card-info">
                              <h3>
                                {p.title}
                                <ArrowUp size={15} />
                              </h3>
                              <span>
                                {p.scene_count || 0} scenes{" "}
                                <span className="separator-dot">·</span> Edited{" "}
                                {new Date(
                                  p.updated * 1000,
                                ).toLocaleDateString()}
                              </span>
                            </div>
                          </button>
                        ))}
                      </div>
                    ) : (
                      <div className="new-project-area">
                        <div className="new-project-copy">
                          <span className="tiny-label">
                            THE BLANK CANVAS IS YOURS
                          </span>
                          <h3>What will you make first?</h3>
                          <p>
                            A short film. A Halloween projection. Something
                            nobody has seen before.
                          </p>
                          <Button
                            primary
                            onClick={() =>
                              connection.token
                                ? setNewOpen(true)
                                : setPairOpen(true)
                            }
                          >
                            <Plus size={16} />
                            Start a production
                          </Button>
                        </div>
                        <div className="starter-card">
                          <span className="starter-icon">✦</span>
                          <h4>A little inspiration</h4>
                          <p>
                            Open an eight-scene Halloween storyboard, ready for
                            your own direction.
                          </p>
                          <button
                            disabled={!connection.token || busy}
                            onClick={() =>
                              newProject(
                                "A Springfield Halloween",
                                "An eight-scene cartoon Halloween window projection. Preserve recognizable characters, dark backgrounds, subtle readable motion and a looping atmosphere.",
                                true,
                              )
                            }
                          >
                            Use Halloween starter <ArrowRight size={15} />
                          </button>
                        </div>
                      </div>
                    )}
                  </section>
                  <section className="studio-status">
                    <div className="section-heading">
                      <div>
                        <h2>Your local studio</h2>
                        <p>A clear view of what’s ready to create.</p>
                      </div>
                      <span className="secure-note">
                        <Lock size={12} /> Private by design
                      </span>
                    </div>
                    <div className="status-grid">
                      <ServiceCard
                        icon={Clapperboard}
                        title="ComfyUI"
                        status={
                          data?.services.comfy.connected
                            ? "Ready to connect workflows"
                            : "Not connected"
                        }
                        detail={
                          data?.services.comfy.version
                            ? `Version ${data.services.comfy.version}`
                            : "Your image & video engine"
                        }
                        good={!!data?.services.comfy.connected}
                      />
                      <ServiceCard
                        icon={Sparkles}
                        title="Ollama"
                        status={
                          data?.services.ollama.connected
                            ? `${data.services.ollama.models.length} models installed`
                            : "Optional · not connected"
                        }
                        detail="Your local creative partner"
                        good={!!data?.services.ollama.connected}
                      />
                      <div className="status-card">
                        <div className="status-card-top">
                          <Zap size={19} />
                          <span>GPU memory</span>
                        </div>
                        <strong>
                          {data?.resources.gpu
                            ? `${fmt(data.resources.gpu.used)} / ${fmt(data.resources.gpu.total)}`
                            : "Connect to monitor"}
                        </strong>
                        <div className="meter">
                          <span
                            style={{
                              width: data?.resources.gpu
                                ? `${(data.resources.gpu.used / data.resources.gpu.total) * 100}%`
                                : "0%",
                            }}
                          />
                        </div>
                        <small>
                          {data?.resources.gpu?.name ||
                            "Actual measurements, never estimates"}
                        </small>
                      </div>
                      <div className="status-card">
                        <div className="status-card-top">
                          <Folder size={19} />
                          <span>Project storage</span>
                        </div>
                        <strong>
                          {data
                            ? `${fmt(data.resources.disk_free)} available`
                            : "Stored on your computer"}
                        </strong>
                        <small>Projects, media, and exports stay local.</small>
                      </div>
                    </div>
                  </section>
                </>
              ) : page === "Settings" ? (
                <SettingsPage
                  project={project}
                  data={data}
                  act={act}
                  onPair={() => setPairOpen(true)}
                />
              ) : page === "Model Library" ? (
                <ModelsPage
                  workflows={models.data || []}
                  data={data}
                  act={act}
                />
              ) : !project ? (
                <Empty
                  title="Choose a production"
                  description="Open a project from your workspace, or start a fresh story."
                  action={
                    <Button primary onClick={() => go("Overview")}>
                      <Folder size={16} />
                      Go to workspace
                    </Button>
                  }
                />
              ) : (
                <>
                  <div className="production-heading">
                    <div>
                      <button
                        className="back-link"
                        onClick={() => go("Overview")}
                      >
                        <ArrowLeft size={14} />
                        All productions
                      </button>
                      <h1>{project.title}</h1>
                      <p>
                        {project.brief ||
                          "Your next story, one scene at a time."}
                      </p>
                    </div>
                    <div
                      className="mode-switch"
                      role="group"
                      aria-label="Production mode"
                    >
                      {MODES.map((m) => (
                        <button
                          title={m.description}
                          key={m.id}
                          className={project.mode === m.id ? "selected" : ""}
                          onClick={() => modeChange(m.id)}
                        >
                          {m.id === "automatic" ? (
                            <Sparkles size={13} />
                          ) : m.id === "hybrid" ? (
                            <WandSparkles size={13} />
                          ) : (
                            <SlidersHorizontal size={13} />
                          )}{" "}
                          {m.name}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="production-controls">
                    <div>
                      <Badge tone="violet">
                        {MODES.find((m) => m.id === project.mode)?.description}
                      </Badge>
                      <span className="muted">
                        {project.scenes.length} scenes ·{" "}
                        {project.settings.audio_mode === "silent"
                          ? "Silent production"
                          : "Audio enabled"}
                      </span>
                    </div>
                    <div className="button-row">
                      <Button
                        onClick={() => produce("stills")}
                        disabled={featurePhase < 2 || busy}
                      >
                        <ImageIcon size={15} />
                        Generate stills
                      </Button>
                      <Button
                        onClick={() => produce("videos")}
                        disabled={featurePhase < 2 || busy}
                      >
                        <Video size={15} />
                        Generate videos
                      </Button>
                      <Button
                        primary
                        onClick={() => produce("all")}
                        disabled={featurePhase < 2 || busy}
                      >
                        <Sparkles size={15} />
                        {project.mode === "manual"
                          ? "Generate all"
                          : "Auto Produce"}
                      </Button>
                      <Button
                        onClick={() =>
                          act(
                            () =>
                              request(`/api/projects/${project.id}/pause`, {}),
                            "The active job can finish; new jobs will wait.",
                          )
                        }
                        disabled={featurePhase < 2}
                      >
                        <Pause size={15} aria-label="Pause new jobs" />
                      </Button>
                    </div>
                  </div>
                  <VisualBible
                    key={project.id}
                    project={project}
                    act={act}
                    renderMedia={(a) => <Media asset={a} />}
                  />
                  {featurePhase >= 3 && (
                    <ProductionSettings
                      key={project.id}
                      project={project}
                      workflows={models.data || []}
                      models={data?.services.ollama.models || []}
                      act={act}
                    />
                  )}
                  {["Storyboard", "Image Studio", "Video Studio"].includes(
                    page,
                  ) ? (
                    <div
                      className={`story-workspace ${scene ? "with-inspector" : ""}`}
                    >
                      <section>
                        <div className="section-heading compact">
                          <div>
                            <h2>
                              {page === "Storyboard" ? "Your storyboard" : page}
                            </h2>
                            <p>
                              {page === "Storyboard"
                                ? "Shape the story. Refine every frame."
                                : "Generate, compare, and select the takes that tell your story."}
                            </p>
                          </div>
                          <Button
                            onClick={() =>
                              act(async () => {
                                const s = await request(
                                  `/api/projects/${project.id}/scenes`,
                                  {
                                    title: `Scene ${project.scenes.length + 1}`,
                                    body: {},
                                  },
                                );
                                setSelected(s.id);
                              }, "Scene added")
                            }
                          >
                            <Plus size={15} />
                            Add scene
                          </Button>
                        </div>
                        {project.scenes.length ? (
                          <div className="scene-grid">
                            {project.scenes.map((s, index) => {
                              const image =
                                s.assets.find(
                                  (a) => a.id === s.selected_image_id,
                                ) || s.assets.find((a) => a.kind === "image");
                              const video = s.assets.find(
                                (a) => a.id === s.selected_video_id,
                              );
                              const job = jobs.find(
                                (j) =>
                                  j.scene_id === s.id &&
                                  !["superseded", "cancelled"].includes(
                                    j.status,
                                  ),
                              );
                              return (
                                <button
                                  className={`scene-card ${selected === s.id ? "selected" : ""}`}
                                  key={s.id}
                                  onClick={() => setSelected(s.id)}
                                >
                                  <div className="scene-poster">
                                    {page === "Video Studio" && video ? (
                                      <Media asset={video} />
                                    ) : image ? (
                                      <Media asset={image} />
                                    ) : (
                                      <div
                                        className={`scene-sketch sketch-${index % 4}`}
                                      >
                                        <span>
                                          SCENE{" "}
                                          {String(index + 1).padStart(2, "0")}
                                        </span>
                                        <Clapperboard size={31} />
                                        <div className="sketch-orb" />
                                      </div>
                                    )}
                                    <span className="scene-number">
                                      {String(index + 1).padStart(2, "0")}
                                    </span>
                                    <span className="scene-duration">
                                      <Clock size={11} />
                                      {s.body.duration || 3}s
                                    </span>
                                    <div className="scene-overlay">
                                      <span>
                                        <Edit3 size={14} />
                                        Direct scene
                                      </span>
                                    </div>
                                  </div>
                                  <div className="scene-card-body">
                                    <div className="scene-title-row">
                                      <h3>{s.title}</h3>
                                      <MoreHorizontal size={17} />
                                    </div>
                                    <p>
                                      {s.body.summary ||
                                        "A new scene, waiting for your direction."}
                                    </p>
                                    <div className="scene-card-footer">
                                      <Badge
                                        tone={
                                          video
                                            ? "green"
                                            : image
                                              ? "cyan"
                                              : job?.status === "failed"
                                                ? "red"
                                                : ""
                                        }
                                      >
                                        {s.body.disabled
                                          ? "Excluded"
                                          : video
                                            ? s.selected_video_id &&
                                              s.video_current === false
                                              ? "Video outdated"
                                              : video.approved
                                                ? "Video ready"
                                                : "Review video"
                                            : image
                                              ? s.selected_image_id &&
                                                s.image_current === false
                                                ? "Still outdated"
                                                : image.approved
                                                  ? "Still ready"
                                                  : "Choose a still"
                                              : job
                                                ? short(job.status)
                                                : "Not started"}
                                      </Badge>
                                      <span>{s.assets.length} takes</span>
                                    </div>
                                  </div>
                                </button>
                              );
                            })}
                          </div>
                        ) : (
                          <Empty
                            title="A story starts with one scene"
                            description="Add a scene, write its prompts, or let your AI Director develop the storyboard."
                            action={
                              <Button onClick={() => go("AI Director")}>
                                <Sparkles size={16} />
                                Open AI Director
                              </Button>
                            }
                          />
                        )}
                      </section>
                      {scene && (
                        <SceneInspector
                          key={scene.id}
                          scene={scene}
                          project={project}
                          workflows={models.data || []}
                          act={act}
                          produce={produce}
                          close={() => setSelected("")}
                        />
                      )}
                    </div>
                  ) : page === "Generation Queue" ? (
                    <QueuePage
                      jobs={jobs.filter((j) => j.project_id === active)}
                      act={act}
                      project={project}
                    />
                  ) : page === "AI Director" ? (
                    <DirectorPage
                      project={project}
                      selectedScene={selected}
                      models={data?.services.ollama.models || []}
                      act={act}
                    />
                  ) : page === "Timeline" ? (
                    <TimelineEditor
                      key={project.id}
                      project={project}
                      act={act}
                      renderMedia={(a) => <Media asset={a} controls />}
                    />
                  ) : page === "Exports" ? (
                    <ExportsPage
                      assets={(data?.assets || []).filter(
                        (a) => a.project_id === active && a.kind === "export",
                      )}
                      project={project}
                      act={act}
                    />
                  ) : null}
                </>
              )}
            </motion.div>
          </AnimatePresence>
          <footer className="page-footer">
            <span>
              SceneFlow AI Studio <span>✦</span> A place for your next great
              story.
            </span>
            <span>{phase}</span>
          </footer>
        </main>
      </div>
      <AnimatePresence>
        {toast && (
          <motion.div
            className="toast"
            role="status"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
          >
            <Check size={17} />
            <span>{toast}</span>
            <button
              aria-label="Dismiss notification"
              onClick={() => setToast("")}
            >
              <X size={15} />
            </button>
          </motion.div>
        )}
      </AnimatePresence>
      {pairOpen && (
        <PairDialog
          close={() => setPairOpen(false)}
          notify={notify}
          refresh={refresh}
        />
      )}
      {newOpen && (
        <ProjectDialog
          close={() => setNewOpen(false)}
          create={newProject}
          busy={busy}
        />
      )}
      {searchOpen && (
        <div className="modal-backdrop" onClick={() => setSearchOpen(false)}>
          <div
            className="command-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Search studio"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="command-input">
              <Search size={19} />
              <input
                autoFocus
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search projects and studio tools…"
              />
              <kbd>ESC</kbd>
            </div>
            {(data?.projects || [])
              .filter((p) =>
                p.title.toLowerCase().includes(search.toLowerCase()),
              )
              .map((p) => (
                <button
                  key={p.id}
                  onClick={() => {
                    choose(p.id);
                    setSearchOpen(false);
                  }}
                >
                  <Folder size={17} />
                  {p.title}
                  <ArrowRight size={14} />
                </button>
              ))}
            {NAV.filter((n) =>
              n[0].toLowerCase().includes(search.toLowerCase()),
            ).map(([name, Icon]) => (
              <button
                key={name}
                onClick={() => {
                  go(name);
                  setSearchOpen(false);
                }}
              >
                <Icon size={17} />
                {name}
                <ArrowRight size={14} />
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ServiceCard({
  icon: Icon,
  title,
  status,
  detail,
  good,
}: {
  icon: LucideIcon;
  title: string;
  status: string;
  detail: string;
  good: boolean;
}) {
  return (
    <div className="status-card">
      <div className="status-card-top">
        <Icon size={19} />
        <span>{title}</span>
        <span className={`status-dot ${good ? "online" : ""}`} />
      </div>
      <strong>{status}</strong>
      <small>{detail}</small>
    </div>
  );
}
function PairDialog({
  close,
  notify,
  refresh,
}: {
  close: () => void;
  notify: (s: string) => void;
  refresh: () => void;
}) {
  const connection = useConnection();
  const [url, setUrl] = useState(connection.url);
  const [code, setCode] = useState(initialPairCode);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  async function connect(e: React.FormEvent) {
    e.preventDefault();
    setWorking(true);
    setError("");
    try {
      const parsed = new URL(url);
      if (
        !["127.0.0.1", "localhost"].includes(parsed.hostname) ||
        parsed.protocol !== "http:"
      )
        throw new Error("Use a loopback address on this computer.");
      connection.set(parsed.origin, "");
      const value = await request("/api/pair", {
        code,
        label: "SceneFlow browser",
      });
      connection.set(parsed.origin, value.token);
      refresh();
      notify("Your private studio is connected.");
      close();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setWorking(false);
    }
  }
  return (
    <div className="modal-backdrop">
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pair-title"
      >
        <button
          className="modal-close"
          aria-label="Close pairing"
          onClick={close}
        >
          <X size={19} />
        </button>
        <div className="modal-symbol">
          <Link2 size={25} />
        </div>
        <span className="eyebrow">YOUR PRIVATE CONNECTION</span>
        <h2 id="pair-title">Bring your studio online.</h2>
        <p>
          Start <code>START_STUDIO.bat</code> on your PC, then enter the pairing
          code from its window. Your files stay on your computer.
        </p>
        <form onSubmit={connect}>
          <label>
            Studio Agent address
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              type="url"
              required
            />
          </label>
          <label>
            Pairing code
            <input
              autoFocus
              value={code}
              onChange={(e) => setCode(e.target.value)}
              autoComplete="off"
              placeholder="Enter your local code"
              required
            />
          </label>
          {error && <div className="inline-error">{error}</div>}
          <Button type="submit" primary disabled={working}>
            {working ? (
              <LoaderCircle className="spin" size={16} />
            ) : (
              <ShieldCheck size={16} />
            )}
            Connect securely
          </Button>
        </form>
        <div className="pair-note">
          <Lock size={14} /> Only your paired browser can access local projects.
        </div>
        <a
          href="http://127.0.0.1:8770"
          target="_blank"
          rel="noreferrer"
          className="text-link"
        >
          Having trouble? Open the local interface <ExternalLink size={13} />
        </a>
      </section>
    </div>
  );
}
function ProjectDialog({
  close,
  create,
  busy,
}: {
  close: () => void;
  create: (title: string, brief: string) => void;
  busy: boolean;
}) {
  const [title, setTitle] = useState("");
  const [brief, setBrief] = useState("");
  const [error, setError] = useState("");
  return (
    <div className="modal-backdrop">
      <section
        className="modal wide"
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-title"
      >
        <button
          className="modal-close"
          aria-label="Close new project"
          onClick={close}
        >
          <X size={19} />
        </button>
        <div className="modal-symbol">
          <Clapperboard size={25} />
        </div>
        <span className="eyebrow">A NEW PRODUCTION</span>
        <h2 id="new-title">Every story starts with a spark.</h2>
        <p>
          Name your project and tell us what you have in mind. You can refine
          everything as you go.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const parsed = z
              .object({
                title: z.string().trim().min(1).max(160),
                brief: z.string().max(30000),
              })
              .safeParse({ title, brief });
            if (!parsed.success) {
              setError("Give your production a title, up to 160 characters.");
              return;
            }
            create(parsed.data.title, brief);
          }}
        >
          <label>
            Project title
            <input
              autoFocus
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="A story worth telling"
              required
            />
          </label>
          <label>
            Your creative brief
            <textarea
              value={brief}
              onChange={(e) => setBrief(e.target.value)}
              placeholder="A moody short film, a Halloween window projection, an idea you can’t stop thinking about…"
              rows={5}
            />
          </label>
          <div className="form-note">
            <WandSparkles size={15} /> Starts in Assisted mode. You can take
            full control at any time.
          </div>
          {error && <div className="inline-error">{error}</div>}
          <Button type="submit" primary disabled={busy}>
            <Plus size={17} />
            Create production
          </Button>
        </form>
      </section>
    </div>
  );
}

function SceneInspector({
  scene,
  project,
  workflows,
  act,
  produce,
  close,
}: {
  scene: Scene;
  project: Project;
  workflows: Workflow[];
  act: any;
  produce: (s: string) => void;
  close: () => void;
}) {
  const draftKey = "sceneflow.draft." + scene.id;
  const [draft] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(draftKey) || "null");
    } catch {
      return null;
    }
  });
  const [title, setTitle] = useState(draft?.title ?? scene.title);
  const [body, setBody] = useState(draft?.body ?? { ...scene.body });
  const [baseRevision, setBaseRevision] = useState(
    draft?.revision ?? scene.revision,
  );
  const [tab, setTab] = useState("Direction");
  const [dirty, setDirty] = useState(!!draft);
  useEffect(() => {
    if (dirty)
      localStorage.setItem(
        draftKey,
        JSON.stringify({ title, body, revision: baseRevision }),
      );
    else localStorage.removeItem(draftKey);
  }, [title, body, dirty]);
  useEffect(() => {
    if (!dirty) {
      setTitle(scene.title);
      setBody({ ...scene.body });
      setBaseRevision(scene.revision);
    }
  }, [scene.revision, dirty]);
  const change = (key: string, value: any) => {
    setBody({ ...body, [key]: value });
    setDirty(true);
  };
  const selectedImage = scene.assets.find(
    (a) => a.id === scene.selected_image_id,
  );
  return (
    <aside className="inspector">
      <div className="inspector-header">
        <span>
          <SlidersHorizontal size={16} /> SCENE INSPECTOR
        </span>
        <button
          className="icon-button"
          aria-label="Close scene inspector"
          onClick={close}
        >
          <X size={17} />
        </button>
      </div>
      <div className="inspector-tabs">
        {["Direction", "Takes", "Settings", "History"].map((t) => (
          <button
            key={t}
            className={tab === t ? "selected" : ""}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>
      <div className="inspector-content">
        {dirty && (
          <p className="muted">
            Draft saved in this browser.{" "}
            {baseRevision !== scene.revision
              ? "A newer scene revision exists; compare before saving."
              : "Save to update pending generation."}{" "}
            <button
              className="text-link"
              onClick={() => {
                setDirty(false);
                setTitle(scene.title);
                setBody({ ...scene.body });
                setBaseRevision(scene.revision);
              }}
            >
              Discard draft
            </button>
          </p>
        )}
        {tab === "Direction" ? (
          <>
            <label>
              Scene title
              <input
                value={title}
                onChange={(e) => {
                  setTitle(e.target.value);
                  setDirty(true);
                }}
              />
            </label>
            <label>
              Scene brief
              <textarea
                rows={3}
                value={body.summary || ""}
                onChange={(e) => change("summary", e.target.value)}
              />
            </label>
            <label>
              <span>
                <ImageIcon size={14} />
                Starting still prompt
              </span>
              <textarea
                rows={6}
                value={body.image_prompt || ""}
                onChange={(e) => change("image_prompt", e.target.value)}
                placeholder="Describe the starting composition, lighting, characters and visual style…"
              />
            </label>
            <label>
              <span>
                <Video size={14} />
                Animation prompt
              </span>
              <textarea
                rows={6}
                value={body.video_prompt || ""}
                onChange={(e) => change("video_prompt", e.target.value)}
                placeholder="Describe what moves, how the camera behaves, and where the action ends…"
              />
            </label>
            <label>
              Negative prompt
              <textarea
                rows={2}
                value={body.negative_prompt || ""}
                onChange={(e) => change("negative_prompt", e.target.value)}
              />
            </label>
            <div className="revision-note">
              <Lock size={12} /> Revision {scene.revision}. Active renders keep
              their original instructions.
            </div>
            {dirty && (
              <p className="muted">
                {body.image_prompt !== scene.body.image_prompt ||
                body.image_workflow !== scene.body.image_workflow
                  ? "This change needs a new still and animation. Earlier takes remain available."
                  : "Motion and timing changes reuse the selected still and need a new animation."}
              </p>
            )}
            <Button
              primary
              disabled={!dirty}
              onClick={() =>
                act(async () => {
                  const result = await request(
                    "/api/scenes/" + scene.id,
                    { revision: baseRevision, title, body },
                    "PATCH",
                  );
                  setDirty(false);
                  setBaseRevision(result.revision);
                  return result;
                }, "New scene revision saved. Active jobs keep their original settings.")
              }
            >
              <Save size={15} />
              Save direction
            </Button>
          </>
        ) : tab === "Settings" ? (
          <>
            <label>
              Image workflow
              <select
                value={body.image_workflow || ""}
                onChange={(e) =>
                  change("image_workflow", e.target.value || null)
                }
              >
                <option value="">Inherit project default</option>
                {workflows
                  .filter((w) => w.task === "text_to_image")
                  .map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name} · {w.status}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Video workflow
              <select
                value={body.video_workflow || ""}
                onChange={(e) =>
                  change("video_workflow", e.target.value || null)
                }
              >
                <option value="">Inherit project default</option>
                {workflows
                  .filter((w) => w.task === "image_to_video")
                  .map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name} · {w.status}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Duration (seconds)
              <input
                type="number"
                min="1"
                max="5"
                value={body.duration || 3}
                onChange={(e) => change("duration", Number(e.target.value))}
              />
            </label>
            <label>
              Seed
              <input
                type="number"
                min="0"
                value={body.seed || 0}
                onChange={(e) => change("seed", Number(e.target.value))}
              />
            </label>
            <Button
              primary
              disabled={!dirty}
              onClick={() =>
                act(async () => {
                  const result = await request(
                    "/api/scenes/" + scene.id,
                    { revision: baseRevision, body },
                    "PATCH",
                  );
                  setDirty(false);
                  setBaseRevision(result.revision);
                  return result;
                }, "Settings saved as a new revision.")
              }
            >
              <Save size={15} />
              Save settings
            </Button>
            <p className="muted">
              Scene overrides are saved independently from project defaults.
            </p>
          </>
        ) : tab === "History" ? (
          <SceneHistory scene={scene} act={act} />
        ) : (
          <>
            <CandidateReview
              scene={scene}
              project={project}
              act={act}
              renderMedia={(a) => <Media asset={a} controls />}
            />
            {scene.assets.length ? (
              scene.assets.map((a) => (
                <div className="take" key={a.id}>
                  <Media asset={a} controls />
                  {a.kind === "image" && (
                    <CorrectionCanvas
                      key={a.id}
                      asset={a}
                      project={project}
                      act={act}
                      renderMedia={(v) => <Media asset={v} controls />}
                    />
                  )}
                  <div>
                    <Badge>{a.kind}</Badge>
                    <Badge tone={a.approved ? "green" : ""}>
                      {a.approved ? "Approved" : "Needs review"}
                    </Badge>
                  </div>
                  <p>Created {new Date(a.created * 1000).toLocaleString()}</p>
                  {featurePhase >= 5 && ["image", "video"].includes(a.kind) && (
                    <AssetQuality asset={a} project={project} act={act} />
                  )}
                  <div className="button-row">
                    <Button
                      onClick={() =>
                        act(
                          () => request(`/api/assets/${a.id}/select`, {}),
                          "Take selected for this scene.",
                        )
                      }
                    >
                      <Check size={14} />
                      Select
                    </Button>
                    <Button
                      onClick={() =>
                        act(
                          () => request(`/api/assets/${a.id}/approve`, {}),
                          "This exact take is approved.",
                        )
                      }
                    >
                      <ShieldCheck size={14} />
                      Approve
                    </Button>
                  </div>
                </div>
              ))
            ) : (
              <Empty
                icon={ImageIcon}
                title="Your takes will appear here"
                description="Generate or import a still to start this scene."
              />
            )}
          </>
        )}
      </div>
      <div className="inspector-footer">
        <div className="button-row">
          <Button
            onClick={() => produce("selected_still")}
            disabled={featurePhase < 2 || dirty}
          >
            <ImageIcon size={15} />
            Generate still
          </Button>
          <Button
            primary
            onClick={() => produce("selected_video")}
            disabled={featurePhase < 2 || dirty || !selectedImage}
          >
            <Play size={15} />
            Animate
          </Button>
        </div>
        {featurePhase >= 4 && (
          <label className="upload-label">
            Import a video take
            <input
              type="file"
              accept=".mp4,.webm,.mkv,.mov"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file)
                  act(
                    () =>
                      upload(
                        `/api/projects/${project.id}/import-media?scene_id=${scene.id}`,
                        file,
                      ),
                    "Video imported into this scene.",
                  );
              }}
            />
          </label>
        )}
        {featurePhase >= 2 && (
          <label className="upload-label">
            <Upload size={14} />
            Import a still
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f)
                  act(
                    () => upload(`/api/scenes/${scene.id}/import`, f),
                    "Still imported and linked to this scene.",
                  );
              }}
            />
          </label>
        )}
      </div>
    </aside>
  );
}

function QueuePage({
  jobs,
  project,
  act,
}: {
  jobs: Job[];
  project: Project;
  act: any;
}) {
  const [reviewed, setReviewed] = useState<Record<string, boolean>>({});
  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <h2>The production floor</h2>
          <p>One GPU workload at a time. Every frame in the right hands.</p>
        </div>
        <Button
          onClick={() =>
            act(
              () => request(`/api/projects/${project.id}/resume`, {}),
              "Production resumed.",
            )
          }
          disabled={featurePhase < 2}
        >
          <Play size={15} />
          Resume
        </Button>
      </div>
      {jobs.length ? (
        jobs.map((j) => (
          <div className="queue-row" key={j.id}>
            <div
              className={`job-symbol ${j.status === "running" ? "glowing" : ""}`}
            >
              {j.kind === "image" ? (
                <ImageIcon size={19} />
              ) : j.kind === "video" ? (
                <Video size={19} />
              ) : (
                <Film size={19} />
              )}
            </div>
            <div className="queue-info">
              <strong>
                {j.snapshot.scene_title || j.snapshot.title || short(j.kind)}
              </strong>
              <span>
                {short(j.kind)} · {j.id.slice(0, 8)}
              </span>
              {j.error && <p className="error-text">{j.error}</p>}
            </div>
            <Badge
              tone={
                j.status === "completed"
                  ? "green"
                  : j.status === "failed"
                    ? "red"
                    : j.status === "running"
                      ? "violet"
                      : ""
              }
            >
              {short(j.status)}
            </Badge>
            <div className="job-progress">
              <div className="meter">
                <span style={{ width: `${j.progress * 100}%` }} />
              </div>
              <span>
                {["image", "video"].includes(j.kind) && j.status !== "completed"
                  ? "Stage "
                  : ""}
                {Math.round(j.progress * 100)}%
              </span>
            </div>
            <Button
              onClick={() =>
                act(
                  () => request(`/api/jobs/${j.id}/retry`, {}),
                  "A new attempt was queued.",
                )
              }
              disabled={!["failed", "cancelled"].includes(j.status)}
              title="Retry with a new attempt"
            >
              <RefreshCw size={14} />
            </Button>
            {j.status === "queued" && (
              <>
                <Button
                  title="Move to front of pending work"
                  onClick={() =>
                    act(
                      () =>
                        request(`/api/jobs/${j.id}/priority`, { priority: 80 }),
                      "Pending job prioritized.",
                    )
                  }
                >
                  <ArrowUp size={14} />
                </Button>
                <Button
                  title="Cancel pending job"
                  onClick={() =>
                    act(
                      () => request(`/api/jobs/${j.id}/cancel`, {}),
                      "Pending job cancelled.",
                    )
                  }
                >
                  <X size={14} />
                </Button>
              </>
            )}
            {["submitted", "reconciling"].includes(j.status) &&
              ["image", "video"].includes(j.kind) && (
                <Button
                  title="Cancel only this Studio-owned render"
                  onClick={() =>
                    act(
                      () => request(`/api/jobs/${j.id}/cancel`, {}),
                      "Targeted cancellation requested. Earlier takes are preserved.",
                    )
                  }
                >
                  Stop this render
                </Button>
              )}
            {j.status === "needs_attention" && (
              <details>
                <summary>Review before retrying</summary>
                <p>
                  Check the original job and its outputs. A retry creates a new
                  attempt with these saved inputs.
                </p>
                <p>Backend prompt: {j.comfy_prompt_id || "not confirmed"}</p>
                <label>
                  <input
                    type="checkbox"
                    checked={!!reviewed[j.id]}
                    onChange={(e) =>
                      setReviewed((v) => ({ ...v, [j.id]: e.target.checked }))
                    }
                  />{" "}
                  I reviewed the original result.
                </label>
                <Button
                  disabled={!reviewed[j.id]}
                  onClick={() =>
                    act(
                      () =>
                        request(`/api/jobs/${j.id}/retry`, {
                          confirm_uncertain: true,
                        }),
                      "A new reviewed attempt was queued.",
                    )
                  }
                >
                  Retry reviewed attempt
                </Button>
              </details>
            )}
            <details>
              <summary>Saved inputs</summary>
              <pre
                style={{
                  maxWidth: 300,
                  maxHeight: 240,
                  overflow: "auto",
                  whiteSpace: "pre-wrap",
                }}
              >
                {JSON.stringify(
                  {
                    scene: j.snapshot.scene_id,
                    revision: j.snapshot.scene_revision,
                    prompt: j.snapshot.positive_prompt,
                    source: j.snapshot.source_asset_id,
                    seed: j.snapshot.seed,
                    workflow: j.snapshot.workflow_id,
                  },
                  null,
                  2,
                )}
              </pre>
            </details>
          </div>
        ))
      ) : (
        <Empty
          icon={Activity}
          title="A quiet moment in the studio"
          description="Generation jobs appear here when you create stills, animate scenes, or export a movie."
        />
      )}
    </section>
  );
}
function DirectorPage({
  project,
  selectedScene,
  models,
  act,
}: {
  project: Project;
  selectedScene?: string;
  models: any[];
  act: any;
}) {
  const [text, setText] = useState("");
  const history = useQuery<any>({
    queryKey: ["director", project.id],
    queryFn: () => request(`/api/projects/${project.id}/director`),
    refetchInterval: 4000,
  });
  const [autoContinue, setAutoContinue] = useState(false);
  const [model, setModel] = useState(project.settings.llm || "");
  const [count, setCount] = useState(4);
  return (
    <div className="director-layout">
      <section className="director-panel">
        <div className="director-intro">
          <span className="director-orb">
            <Sparkles size={29} />
          </span>
          <span className="eyebrow">YOUR CREATIVE COLLABORATOR</span>
          <h2>Let’s find the story.</h2>
          <p>
            Brainstorm a new direction, develop a storyboard, or refine one
            moment. Your local AI works with your project’s creative context.
          </p>
        </div>
        {history.data?.chat.map((m: any) => (
          <div className="director-answer" key={m.id}>
            <span className="tiny-label">
              {m.role === "user" ? "YOU" : "DIRECTOR"}
            </span>
            <p style={{ whiteSpace: "pre-wrap" }}>{m.content}</p>
          </div>
        ))}
        {history.data?.proposals
          .filter((p: any) => p.status === "pending")
          .map((p: any) => (
            <article className="panel" key={p.id}>
              <h3>
                {p.kind === "plan"
                  ? "Proposed storyboard"
                  : "Proposed creative changes"}
              </h3>
              <p>{p.body.synopsis || p.body.reply}</p>
              <details>
                <summary>Review every proposed change</summary>
                <pre
                  style={{
                    whiteSpace: "pre-wrap",
                    overflowWrap: "anywhere",
                    maxHeight: 400,
                    overflowY: "auto",
                  }}
                >
                  {JSON.stringify(p.body, null, 2)}
                </pre>
              </details>
              <div className="button-row">
                <Button
                  primary
                  onClick={() =>
                    act(async () => {
                      await request(
                        `/proposals/${p.id}/apply`.replace(
                          "/proposals",
                          "/api/proposals",
                        ),
                        {},
                      );
                      history.refetch();
                    }, "Creative changes saved as new revisions.")
                  }
                >
                  Apply reviewed proposal
                </Button>
                <Button
                  onClick={() =>
                    act(async () => {
                      await request(`/api/proposals/${p.id}/dismiss`, {});
                      history.refetch();
                    }, "Proposal dismissed.")
                  }
                >
                  Dismiss
                </Button>
              </div>
            </article>
          ))}
        <form
          className="director-composer"
          onSubmit={(e) => {
            e.preventDefault();
            act(async () => {
              await request(`/api/projects/${project.id}/director`, {
                model,
                message: text,
                scene_id: selectedScene || null,
              });
              setText("");
              history.refetch();
            }, "Director request queued. Follow progress in Generation Queue.");
          }}
        >
          <textarea
            aria-label="Message your Director"
            rows={4}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="What if the final scene connected back to the opening?"
          />
          <div>
            <select
              aria-label="Creative planning model"
              value={model}
              onChange={(e) => setModel(e.target.value)}
            >
              <option value="">Select an installed model</option>
              {models.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name}
                </option>
              ))}
            </select>
            <Button
              type="submit"
              aria-label="Send to Director"
              primary
              disabled={featurePhase < 3 || !model || !text}
            >
              <ArrowUp size={17} />
            </Button>
          </div>
        </form>
        <p className="director-privacy">
          <Lock size={12} /> All conversations stay on this computer. GPU
          requests wait for a safe window.
        </p>
      </section>
      <aside className="panel director-context">
        <span className="tiny-label">THE CREATIVE BRIEF</span>
        <h3>{project.title}</h3>
        <p>{project.brief || "Add a creative brief in project settings."}</p>
        <div className="divider" />
        <h4>Develop your storyboard</h4>
        <label>
          Number of scenes
          <input
            type="number"
            min="1"
            max="40"
            value={count}
            onChange={(e) => setCount(Number(e.target.value))}
          />
        </label>
        <Button
          primary
          disabled={featurePhase < 3 || !model}
          onClick={() =>
            act(
              () =>
                request(`/api/projects/${project.id}/plan`, {
                  model,
                  scene_count: count,
                  auto_apply: autoContinue,
                  auto_continue: autoContinue,
                }),
              "Planning queued for the next safe GPU window.",
            )
          }
        >
          <WandSparkles size={16} />
          Plan storyboard
        </Button>
        {project.mode === "automatic" && !project.scenes.length && (
          <label>
            <input
              type="checkbox"
              checked={autoContinue}
              onChange={(e) => setAutoContinue(e.target.checked)}
            />{" "}
            Apply the new plan and continue through production
          </label>
        )}
        <p className="muted">
          The AI proposes a structured plan. You keep the final say.
        </p>
      </aside>
    </div>
  );
}
function ExportsPage({
  assets: initialAssets,
  project,
  act,
}: {
  assets: Asset[];
  project: Project;
  act: any;
}) {
  const [page, setPage] = useState(1);
  useEffect(() => setPage(1), [project.id]);
  const history = useQuery<{
    items: Asset[];
    has_more: boolean;
    total: number;
  }>({
    queryKey: ["exports", project.id, page],
    queryFn: () => request(`/api/projects/${project.id}/exports?page=${page}`),
    refetchInterval: 15000,
  });
  const assets = history.data?.items || initialAssets;
  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <h2>Ready for the screen</h2>
          <p>Verified movies, with a complete history of how they were made.</p>
        </div>
        <Button
          primary
          disabled={featurePhase < 2}
          onClick={() =>
            act(
              () => request(`/api/projects/${project.id}/export`, {}),
              "Export queued with a frozen copy of your timeline.",
            )
          }
        >
          <Download size={15} />
          Export movie
        </Button>
      </div>
      {assets.length ? (
        <div className="export-grid">
          {assets.map((a) => (
            <div className="export-card" key={a.id}>
              <Media asset={a} controls />
              <h3>{a.metadata.title || "Final movie"}</h3>
              {a.metadata.timeline_revision !== project.timeline?.revision && (
                <Badge>Earlier timeline revision</Badge>
              )}
              <p>
                {a.metadata.width} × {a.metadata.height} ·{" "}
                {Number(a.metadata.duration || 0).toFixed(2)}s
              </p>
              <a
                className="text-link"
                onClick={async (e) => {
                  e.preventDefault();
                  const result = await request(
                    `/api/assets/${a.id}/ticket`,
                    {},
                  );
                  window.open(
                    useConnection.getState().url + result.url,
                    "_blank",
                    "noopener",
                  );
                }}
                href="#"
              >
                Open movie <ExternalLink size={14} />
              </a>
            </div>
          ))}
        </div>
      ) : (
        <Empty
          icon={Download}
          title="Your premiere is ahead"
          description="When your timeline is ready, export a high-quality MP4. Generation and export settings stay independent."
        />
      )}
      <div className="button-row">
        <button
          className="button"
          disabled={page === 1}
          onClick={() => setPage((p) => p - 1)}
        >
          Newer exports
        </button>
        <span>
          Page {page} · {history.data?.total ?? assets.length} movies
        </span>
        <button
          className="button"
          disabled={!history.data?.has_more}
          onClick={() => setPage((p) => p + 1)}
        >
          Older exports
        </button>
      </div>
    </section>
  );
}
function ModelsPage({
  workflows,
  data,
  act,
}: {
  workflows: Workflow[];
  data?: Bootstrap;
  act: any;
}) {
  return (
    <section>
      {featurePhase >= 4 && <WorkflowImporter act={act} />}
      <div className="section-heading">
        <div>
          <span className="eyebrow">YOUR CREATIVE TOOLKIT</span>
          <h1>Model library</h1>
          <p>
            Installed files are only the beginning. A workflow must be
            compatible before it can create.
          </p>
        </div>
        <Button
          disabled={featurePhase < 2}
          onClick={() =>
            act(
              () => request("/api/workflows/discover", {}),
              "Local workflow inventory refreshed.",
            )
          }
        >
          <RefreshCw size={15} />
          Refresh discovery
        </Button>
      </div>
      {workflows.length ? (
        <div className="model-grid">
          {workflows.map((w) => (
            <div key={w.id} className="panel model-card">
              <div className="model-icon">
                {w.task === "image_to_video" ? <Video /> : <ImageIcon />}
              </div>
              <Badge tone={w.status === "ready" ? "green" : ""}>
                {w.tested ? "Generation verified" : w.status}
              </Badge>
              <h3>{w.name}</h3>
              <p>
                {w.family} · {short(w.task)}
              </p>
              {w.reasons.map((r, i) => (
                <p key={i} className="muted">
                  {r}
                </p>
              ))}
              <div className="model-capabilities">
                {Object.entries(w.capabilities)
                  .filter(([k, v]) => v === true)
                  .map(([k]) => (
                    <Badge key={k}>{short(k)}</Badge>
                  ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <Empty
          icon={Clapperboard}
          title="Discover your local generators"
          description={
            featurePhase < 2
              ? "Workflow discovery is scheduled for the next build phase."
              : "Start ComfyUI and refresh discovery to verify installed models and required nodes."
          }
        />
      )}
      <section className="panel section">
        <h3>Local language models</h3>
        <p>
          Planning and visual quality control have independent selectors.
          Nothing is downloaded automatically.
        </p>
        <div className="model-capabilities">
          {data?.services.ollama.models.map((m) => (
            <Badge key={m.name}>{m.name}</Badge>
          )) || <span className="muted">Ollama is not connected.</span>}
        </div>
      </section>
    </section>
  );
}
function SettingsPage({
  data,
  act,
  onPair,
  project,
}: {
  data?: Bootstrap;
  act: any;
  onPair: () => void;
  project?: Project;
}) {
  const [comfy, setComfy] = useState(
    data?.settings.comfy_url || "http://127.0.0.1:8188",
  );
  const [ollama, setOllama] = useState(
    data?.settings.ollama_url || "http://127.0.0.1:11434",
  );
  const [pairCode, setPairCode] = useState("");
  const [diagnostic, setDiagnostic] = useState<any>(null);
  return (
    <section className="settings-page">
      <span className="eyebrow">MAKE YOURSELF AT HOME</span>
      <h1>Studio settings</h1>
      <p>Your connections, your tools, your creative space.</p>
      <div className="panel settings-panel">
        <h3>
          <Monitor size={18} />
          Local connections
        </h3>
        <label>
          ComfyUI address
          <input value={comfy} onChange={(e) => setComfy(e.target.value)} />
        </label>
        <label>
          Ollama address
          <input value={ollama} onChange={(e) => setOllama(e.target.value)} />
        </label>
        <div className="button-row">
          <Button
            primary
            disabled={!data}
            onClick={() =>
              act(
                () =>
                  request(
                    "/api/settings",
                    { comfy_url: comfy, ollama_url: ollama },
                    "PATCH",
                  ),
                "Connection settings saved.",
              )
            }
          >
            <Save size={15} />
            Save connections
          </Button>
          <Button onClick={onPair}>
            <Link2 size={15} />
            Pair browser
          </Button>
          <Button
            disabled={!data}
            onClick={() =>
              act(async () => {
                const result = await request("/api/session/pair-code", {});
                setPairCode(result.code);
              }, "New one-use code created; it expires in ten minutes.")
            }
          >
            Create code for another browser
          </Button>
        </div>
        {pairCode && (
          <p>
            One-use pairing code: <strong>{pairCode}</strong> · expires in 10
            minutes
          </p>
        )}
      </div>
      <div className="panel settings-panel">
        <h3>
          <ShieldCheck size={18} />
          Privacy & resources
        </h3>
        <div className="setting-row">
          <div>
            <strong>Storage stays local</strong>
            <p>
              Projects, original media, credentials, and exports are excluded
              from GitHub.
            </p>
          </div>
          <Badge tone="green">Local only</Badge>
        </div>
        <div className="setting-row">
          <div>
            <strong>Conservative GPU scheduling</strong>
            <p>
              One GPU-intensive job at a time. Other apps’ jobs are never
              interrupted.
            </p>
          </div>
          <Badge>Conservative</Badge>
        </div>
        <div className="setting-row">
          <div>
            <strong>AI quality checking</strong>
            <p>
              Off by default. Enable a verified vision model in project
              settings.
            </p>
          </div>
          <Badge>Optional</Badge>
        </div>
        <div className="setting-row">
          <div>
            <strong>System RAM</strong>
            <p>
              {data
                ? `${fmt(data.resources.ram_available)} available of ${fmt(data.resources.ram_total)}`
                : "Connect your agent for actual measurements."}
            </p>
          </div>
          <Badge>{data ? "Observed" : "Unknown"}</Badge>
        </div>
      </div>
      <div className="panel settings-panel">
        <h3>About this build</h3>
        <p>
          {phase}. Features become available as verified phases are released.
        </p>
        <a
          className="text-link"
          href="https://github.com/RorriMaesu/sceneflow-ai-studio"
          target="_blank"
          rel="noreferrer"
        >
          Source & release notes <ExternalLink size={13} />
        </a>
      </div>
      {featurePhase >= 4 && <BackupPanel project={project} act={act} />}
      {featurePhase >= 5 && (
        <section className="panel settings-panel">
          <h3>Setup & readiness</h3>
          <ol>
            <li>
              Open START_STUDIO.bat. It starts available local services and
              opens your private studio.
            </li>
            <li>
              Pair this browser with the one-use local code. If your browser
              asks, allow local-network access for this studio.
            </li>
            <li>
              Refresh discovery in Model Library, then choose planning, image
              and video models independently.
            </li>
            <li>
              Open a project, review the still first, and animate that exact
              frame. Optional AI quality checking starts off.
            </li>
          </ol>
          <div className="button-row">
            <Button
              onClick={() =>
                act(
                  async () => setDiagnostic(await request("/api/diagnostics")),
                  "Readiness check complete.",
                )
              }
            >
              Run readiness check
            </Button>
            <Button
              disabled={!diagnostic}
              onClick={() => {
                const link = document.createElement("a");
                const url = URL.createObjectURL(
                  new Blob([JSON.stringify(diagnostic, null, 2)], {
                    type: "application/json",
                  }),
                );
                link.href = url;
                link.download = "SceneFlow-diagnostics.json";
                link.click();
                window.setTimeout(() => URL.revokeObjectURL(url), 1000);
              }}
            >
              Download diagnostics
            </Button>
            <Button
              onClick={() =>
                act(async () => {
                  await request("/api/session/revoke", {});
                  useConnection.getState().disconnect();
                }, "This browser session was revoked.")
              }
            >
              Revoke this browser
            </Button>
          </div>
          {diagnostic && (
            <pre
              style={{
                whiteSpace: "pre-wrap",
                maxHeight: 360,
                overflow: "auto",
              }}
            >
              {JSON.stringify(diagnostic, null, 2)}
            </pre>
          )}
        </section>
      )}
    </section>
  );
}
const EXAMPLE = [
  [
    "Homer’s Worst Nightmare",
    "Homer nervously holds a glowing jack-o-lantern as red eyes blink behind him",
  ],
  [
    "Bart’s Chainsaw Prank",
    "Bart reveals a theatrical toy chainsaw with a mischievous grin",
  ],
  [
    "Maggie’s Demonic Transformation",
    "Maggie’s innocent expression changes into a playful supernatural glow",
  ],
  [
    "Mr. Burns the Vampire",
    "Mr. Burns slowly opens his cape beneath a violet moon",
  ],
  [
    "Groundskeeper Willie’s Nightmare",
    "Willie watches a shadow move behind a crooked garden fence",
  ],
  [
    "Homer’s Possessed Donut",
    "A floating donut glows as Homer stares in comic disbelief",
  ],
  [
    "Marge’s Witchcraft",
    "Marge stirs a gently bubbling cauldron with green candlelight",
  ],
  [
    "Lisa’s Skeleton Xylophone",
    "Lisa plays a little skeleton xylophone as its bones softly glow",
  ],
];

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      <Studio />
    </QueryClientProvider>
  </React.StrictMode>,
);
