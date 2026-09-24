#!/usr/bin/env bash
# The request's paths through the screens, on the demo data. Each path
# works on its own FAM document, so all five run on one fresh copy.
#
#   SK=<this skill's folder> SCRATCH=<folder with signed-dcr.pdf,
#   signed-dcr-rescan.pdf, signed-pages.png> OUT=<screenshots> \
#     bash paths.sh effective return withdraw deny custodian-return
#
# Prints each step's non-routine lines (TEXT, VALUE, ERRORS, FAIL) and
# stops a path at its first failing step.

D="$SK/drives/demo"
export SCRATCH

step() {
  local name="$1"; shift
  local out code
  out=$(env "$@" node "$SK/cdp.mjs" "$D/$name.cdp" "$OUT" 2>&1); code=$?
  printf '  %-20s %s ok, %s\n' "$name" "$(grep -c '^ok' <<<"$out")" \
    "$( [ $code = 0 ] && echo passed || echo FAILED)"
  grep '^TEXT\|^VALUE\|^FAIL\|^ERRORS\|^skip' <<<"$out" | sed 's/^/      /'
  return $code
}

path_effective() {   # draft to effective, with a corrected starting status
  local P=(DOC="FAM 6.02" SECTION="2.0 SCOPE" TAG=eff-
    REASON="The LNU Dormitory now bills its residents through the Accounting Office, so its receivables fall within these procedures."
    TEXT="These procedures apply to all accounts receivable arising from the official transactions of the University such as from the operations of the LNU House, of the LNU Dormitory, of the LNU Cafeteria, and Inter-Agency transaction with the Commission on Higher Education (CHED) for the implementation of the Free Higher Education, among others.")
  step draft "${P[@]}" && step submit "${P[@]}" &&
  step concur "${P[@]}" WHO=BUD_Jose && step concur "${P[@]}" WHO=CMO_Carlo &&
  step signed-copies "${P[@]}" && step imr-accept "${P[@]}" && step approval "${P[@]}" &&
  step custodian-baseline "${P[@]}" &&
  step custodian-effective "${P[@]}" VERSION=01 REVISION=3 &&
  step reader "${P[@]}"
}

path_return() {      # returned, redrafted, re-checked, resubmitted, locked on version 2
  local P=(DOC="FAM 6.03" SECTION="1.0 OBJECTIVES" TAG=ret-
    REASON="The objectives now include supporting the annual budget."
    TEXT="1.1 To provide information about the financial position, financial performance, and cash flows of the University that are useful for decision-making.\n1.2 To demonstrate accountability of the resources entrusted to the University.\n1.3 To support the preparation of the annual budget."
    FEEDBACK="Preparing the budget belongs in FAM 5.01. Say instead that the statements reach the oversight agencies on time."
    TEXT2="1.1 To provide information about the financial position, financial performance, and cash flows of the University that are useful for decision-making.\n1.2 To demonstrate accountability of the resources entrusted to the University.\n1.3 To ensure the timely submission of financial statements to oversight agencies.")
  step draft "${P[@]}" && step submit "${P[@]}" &&
  step concur "${P[@]}" WHO=CMO_Carlo &&
  step return "${P[@]}" &&
  step redraft "${P[@]}" && step submit "${P[@]}" TAG=ret-v2- &&
  step concur "${P[@]}" WHO=BUD_Jose TAG=ret-v2- && step concur "${P[@]}" WHO=CMO_Carlo TAG=ret-v2-
}

path_withdraw() {    # submitted, then withdrawn; the section is free again
  local P=(DOC="FAM 6.01" SECTION="1.0 OBJECTIVE" TAG=wd-
    REASON="The services now reach employees as well as students."
    TEXT="1.1 To provide guidelines and procedures of accounting services to the students and employees of the University."
    WITHDRAW_REASON="The Accounting Office will fold this into the 2027 revision.")
  step draft "${P[@]}" && step submit "${P[@]}" && step withdraw "${P[@]}" &&
  step draft "${P[@]}" TAG=wd-again-
}

path_deny() {        # denied by the IMR; every office reads why; the section is free again
  local P=(DOC="FAM 5.01" SECTION="1.0 OBJECTIVES" TAG=deny-
    REASON="Offices should know when their budget ceilings arrive."
    TEXT="1.1 To provide guidelines and procedures in monitoring, accounting and reporting of the budget.\n1.2 To ensure that proper and adequate monitoring strategies are in place.\n1.3 To release budget ceilings to offices within five working days."
    DENIAL="Budget ceilings are released when the Board approves them; a five-day promise is not this office's to make.")
  step draft "${P[@]}" && step submit "${P[@]}" &&
  step concur "${P[@]}" WHO=BUD_Jose && step concur "${P[@]}" WHO=CMO_Carlo &&
  step signed-copies "${P[@]}" && step imr-deny "${P[@]}" &&
  step denial-seen "${P[@]}" WHO=ACC_Juan TAB="From my office" &&
  step denial-seen "${P[@]}" WHO=BUD_Jose TAB="Other offices' requests" &&
  step denial-seen "${P[@]}" WHO=CMO_Carlo TAB="Other offices' requests" &&
  step draft "${P[@]}" TAG=deny-again-
}

path_custodian_return() {   # returned for a defect, the named copy replaced, then effective
  local P=(DOC="FAM 4.02" SECTION="1.0 OBJECTIVES" TAG=cr-
    REASON="The guidelines are now reviewed every year."
    TEXT="1.1 To provide guidelines on the income generating projects of LNU.\n1.2 To ensure that these guidelines and policies are followed, maintained and reviewed each year.")
  step draft "${P[@]}" && step submit "${P[@]}" &&
  step concur "${P[@]}" WHO=BUD_Jose && step concur "${P[@]}" WHO=CMO_Carlo &&
  step signed-copies "${P[@]}" && step imr-accept "${P[@]}" && step approval "${P[@]}" &&
  step custodian-return "${P[@]}" && step office-fixes "${P[@]}" &&
  step custodian-effective "${P[@]}" VERSION=01 REVISION=1
}

status=0
for name in "$@"; do
  echo "== $name"
  "path_${name//-/_}" || { echo "== $name: FAILED"; status=1; continue; }
  echo "== $name: passed"
done
exit $status
