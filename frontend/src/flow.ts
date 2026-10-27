import type { Project, Scene, Job } from "./types";
export const STEPS = [
  ["Storyboard", "Story"],
  ["Image Studio", "Look & photos"],
  ["Video Studio", "Motion"],
  ["Timeline", "Edit"],
  ["Exports", "Save video"],
] as const;
export const PAGE_NAMES: Record<string, string> = {
  Overview: "My productions",
  Storyboard: "Story",
  "Image Studio": "Look & photos",
  "Video Studio": "Motion",
  Timeline: "Edit",
  Exports: "Save video",
  "Generation Queue": "Activity",
  "AI Director": "Ask the Director",
  "Model Library": "Advanced tools",
  Settings: "Settings",
  Setup: "Setup & downloads",
  Help: "Help",
};
export const photo = (s: Scene) =>
  s.assets.find((a) => a.id === s.selected_image_id);
export const clip = (s: Scene) =>
  s.assets.find((a) => a.id === s.selected_video_id);
export const currentPhoto = (s: Scene) =>
  !!photo(s) && s.image_current !== false;
export const currentClip = (s: Scene) => !!clip(s) && s.video_current !== false;
export function nextStep(project: Project, jobs: Job[]) {
  const scenes = project.scenes.filter((s) => !s.body.disabled);
  const pending = jobs.some(
    (j) =>
      j.project_id === project.id &&
      ["running", "submitted", "queued", "reconciling"].includes(j.status),
  );
  if (pending)
    return {
      page: "Generation Queue",
      label: "See progress",
      detail:
        "Your requested work is in Activity. You can keep editing other scenes.",
    };
  if (!scenes.length)
    return {
      page: "Storyboard",
      label: "Plan my scenes",
      detail: "Describe your idea, then review the suggested scenes.",
    };
  const needPhoto = scenes.filter((s) => !currentPhoto(s));
  if (needPhoto.length)
    return {
      page: "Image Studio",
      label: "Choose starting photos",
      detail: `${needPhoto.length} scene${needPhoto.length === 1 ? " needs" : "s need"} a current starting photo.`,
    };
  if (scenes.some((s) => !photo(s)?.approved))
    return {
      page: "Image Studio",
      label: "Review starting photos",
      detail: "Choose the exact photos to animate.",
    };
  if (scenes.some((s) => !currentClip(s) || !clip(s)?.approved))
    return {
      page: "Video Studio",
      label: "Create or review clips",
      detail: "Turn your chosen photos into moving scenes.",
    };
  if (!project.timeline?.clips?.length)
    return {
      page: "Timeline",
      label: "Arrange my video",
      detail:
        "Build an edit from your chosen clips, then add sound if you want it.",
    };
  return {
    page: "Exports",
    label: "Save my video",
    detail: "Create a finished file from your saved edit.",
  };
}
export function neededScenes(project: Project, kind: "image" | "video") {
  return project.scenes.filter(
    (s) =>
      !s.body.disabled &&
      (kind === "image"
        ? !currentPhoto(s) &&
          !s.assets.some(
            (a) =>
              a.kind === "image" &&
              a.metadata.role !== "edit_mask" &&
              a.metadata.scene_revision_id === s.revision_id,
          )
        : currentPhoto(s) && !!photo(s)?.approved && !currentClip(s)),
  );
}
