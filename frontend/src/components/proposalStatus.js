// What a request's status is called, and how it reads at a glance.
// One copy, shared by the staff, admin and QMS screens: three copies of a
// list that grows each phase would drift apart.

export const STATUS_LABEL = {
  draft: "Draft",
  concurrence: "Out for concurrence",
  locked: "Locked",
  awaiting_signature: "Awaiting signature",
  ready_for_imr: "Ready for the IMR",
  awaiting_approval: "Awaiting the approving authority",
  with_custodian: "With the Document Custodian",
  package_returned: "Returned for package defects",
  effective: "Effective",
  denied: "Denied",
  withdrawn: "Withdrawn",
};

// Agreed and frozen, still on its way.
export const FROZEN = [
  "locked", "awaiting_signature", "ready_for_imr",
  "awaiting_approval", "with_custodian", "package_returned",
];

// Every status in which the generated documents exist to be shown.
export const WITH_PACKAGE = [
  "awaiting_signature", "ready_for_imr", "awaiting_approval",
  "with_custodian", "package_returned", "effective", "denied",
];

// Still in progress, for list filters. Named, so a new finished status
// does not arrive in "In progress" by default.
export const IN_PROGRESS = ["draft", "concurrence", ...FROZEN];

// The status-mark modifier: agreed or done, stopped, or still moving.
export function statusTone(status) {
  if (status === "effective" || FROZEN.includes(status)) return "approved";
  if (status === "withdrawn" || status === "denied") return "returned";
  return "pending";
}
