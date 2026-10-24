/**
 * Previous and Next under a paged list (50 a page, spec §11.1), with
 * where the reader is. Nothing at all when everything fits on one page.
 */
export default function Pager({ paging, onPage }) {
  if (!paging || paging.pages <= 1) return null;
  const first = (paging.page - 1) * paging.page_size + 1;
  const last = Math.min(paging.page * paging.page_size, paging.count);
  return (
    <div className="pager">
      <button type="button" className="btn btn-ghost btn-sm" disabled={paging.page <= 1}
              onClick={() => onPage(paging.page - 1)}>
        Previous
      </button>
      <span className="subtle text-xs">
        {first.toLocaleString()}–{last.toLocaleString()} of {paging.count.toLocaleString()}
      </span>
      <button type="button" className="btn btn-ghost btn-sm" disabled={paging.page >= paging.pages}
              onClick={() => onPage(paging.page + 1)}>
        Next
      </button>
    </div>
  );
}
