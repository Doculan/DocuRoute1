// One stroke-icon set for every button, so icons share weight, size and
// colour (they inherit currentColor) instead of mixing emoji and glyphs.
const PATHS = {
  plus: "M12 5v14M5 12h14",
  back: "M19 12H5M11 18l-6-6 6-6",
  forward: "M5 12h14M13 6l6 6-6 6",
  close: "M6 6l12 12M18 6L6 18",
  check: "M5 12.5l4.5 4.5L19 7.5",
  refresh: "M20 11a8 8 0 0 0-14.5-4M4 4v4h4M4 13a8 8 0 0 0 14.5 4M20 20v-4h-4",
  edit: "M4 20h4L19 9l-4-4L4 16v4zM13.5 6.5l4 4",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 12h10l1-12M9 7V4h6v3",
  external: "M14 4h6v6M20 4l-9 9M18 14v5H5V6h5",
  download: "M12 4v11M7 11l5 5 5-5M5 20h14",
  upload: "M12 16V5M7 9l5-5 5 5M5 20h14",
  doc: "M7 3h7l4 4v14H7zM14 3v4h4M9.5 12h5M9.5 16h5",
  compare: "M7 4L3 8l4 4M3 8h14M17 20l4-4-4-4M21 16H7",
  merge: "M6 4v6a6 6 0 0 0 6 6h6M18 4v6M15 13l3 3-3 3",
  move: "M12 3v18M12 3l-4 4M12 3l4 4M12 21l-4-4M12 21l4-4",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  ban: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM5.6 5.6l12.8 12.8",
  undo: "M9 14L4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3",
  logout: "M10 4H5v16h5M15 8l4 4-4 4M19 12H9",
};

export default function Icon({ name, size = 15 }) {
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
