// Where am I, what am I looking for, what is waiting for me.
//
// The sidebar says which section you are in; the breadcrumb repeats it at
// the top of the reading column so the answer is next to the content rather
// than parked in the corner. Search and the pending count sit here because
// they belong to the whole app, not to whichever page is open.

export default function Topbar({
  crumb,
  search,
  onSearchChange,
  onSearchSubmit,
  searchPlaceholder = "Search manuals, sections, people",
  pendingCount = 0,
  pendingTitle = "Items waiting for review",
  onPendingClick,
}) {
  return (
    <header className="topbar">
      <div className="crumb">
        QMS <span className="crumb-sep">/</span> <strong>{crumb}</strong>
      </div>

      {onSearchChange && (
        <form
          className="topbar-search"
          onSubmit={(e) => {
            e.preventDefault();
            onSearchSubmit?.(search);
          }}
        >
          <span className="mag" aria-hidden="true">⌕</span>
          <input
            type="search"
            value={search}
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder}
            onChange={(e) => onSearchChange(e.target.value)}
          />
        </form>
      )}

      {pendingCount > 0 && (
        <button
          className="topbar-btn"
          type="button"
          title={pendingTitle}
          aria-label={`${pendingCount} ${pendingTitle}`}
          onClick={onPendingClick}
        >
          ◔
          <span className="topbar-dot">{pendingCount > 99 ? "99+" : pendingCount}</span>
        </button>
      )}
    </header>
  );
}
