# EAOP 08F · Owner keyboard sweep

Scope: P18L659 only. Starting checkout `64a096b425a9ecb610c3a251271acf8cced51045`. Disposable run `20261116-174715-a764`; Apex Tenant administrator on the Windows desktop browser. Two synthetic Apex incidents and approval requests were prepared for the interactive checks. Fixture creation does not count as manual evidence.

Carried forward PASS: Tab reached Refresh, Shift+Tab returned to Evaluation Dashboard, and the owner observed a visible focus ring on both. The current screenshot also shows the Apex administrator on Overview with a visible ring around Refresh. The focus route leading to that screenshot was not supplied.

The owner reported reaching Refresh, all 13 role-visible sidebar links, Sign out, Skip to content, and controls in the browser chrome. The supplied sidebar list was in display order, so it did not establish the exact reverse traversal order. The owner also reported Overview content links (Open Audit Logs, both ticket links, Open Customer Onboarding, Awaiting ticket approval, and Awaiting incident review) before returning to Refresh. A separate screenshot confirmed visible focus on Skip to content. After Enter, the owner reported no apparent change and mentioned underlined Open Audit Logs. An underlined link alone is not proof of focus. Visible landing feedback failed the owner check; the actual focus destination is not observed.

The owner clarified that Open Audit Logs was not outlined, observed no ring on an initial Tab after Enter, and later reported Refresh on Tab. This establishes that keyboard navigation resumed, but does not independently confirm the immediate landing target. From Overview Refresh, a separate single Shift+Tab landed on Administration with a visible ring (PASS). In a controlled forward sweep the owner reported all 13 sidebar links in displayed order, Overview through Administration (PASS for sidebar order). The owner did not separately enumerate visible indicators per route or traverse the content controls inside all 13 routes.

From Administration, seven Shift+Tab presses reached Incident Explorer (PASS for this reverse segment). Enter opened Incident Explorer (PASS for sidebar link activation). A subsequent Tab reached Fault report (PASS for form-field reachability). The owner then tabbed to P-102 and selected it with Enter, observing its mechanical vibration detail (PASS for keyboard selection). The owner did not explicitly confirm an indicator on these specific controls or the immediate focus targets after either Enter.

On the P-101 approval, the owner tabbed to Approve, opened the confirmation with Enter, and reported initial focus on Cancel. Two Tab presses moved focus to Approve and wrapped to Cancel. Escape closed the dialog and the owner reported focus returned to the page's Approve button. Reopening returned initial focus to Cancel, and Shift+Tab wrapped to the dialog's Approve button. The owner confirmed via Enter and supplied a screenshot of the approval notice with only P-102 awaiting decision. PASS for keyboard approval, modal entry and both directions of wrapping, Escape and cancellation focus return. The owner reported “no focus” after successful approval (FAIL for immediate visible focus restoration after confirmation; actual focus target not observed). The owner could then Tab to P-102 Reject.

On P-102, the owner tabbed to Reject, pressed Enter, reported initial focus on Cancel, then tabbed to Reject and confirmed with Enter. The owner reported “Rejected. this ticket will never be submitted/ no focus.” PASS for keyboard rejection; FAIL for immediate visible focus restoration on successful rejection. The owner named the modal controls but did not explicitly describe their indicators.

After rejection, the next Tab went to the browser's Tab Search. Continued Tab returned to the page's Skip to content link. PASS for keyboard escape and re-entry on this observed path. This does not establish the absence of traps inside every route.

On a separate visit to Incident Explorer, the owner tabbed to Fault report and explicitly confirmed both a visible border ring and a text caret (PASS). The session-expiry notice appeared before this final field check.

| Check | Result | Observed scope |
| --- | --- | --- |
| Skip link reachability and visible focus | PASS | Shift+Tab reached the visible Skip to content link, with a screenshot of its ring. |
| Skip-link landing feedback | FAIL | Enter produced no visible focus landing. The actual focus destination is NOT OBSERVED. A later Tab reached Refresh. |
| Forward Tab order across main routes | PASS | All 13 Apex administrator sidebar links were reported in order, Overview through Administration. |
| Content Tab order within all main routes | NOT OBSERVED | Overview, Incident Explorer and Approval Queue were exercised in detail. The content sequences of other pages were not recorded. |
| Shift+Tab reverse order | PASS on checked segments | Refresh to Administration, Administration back to Incident Explorer in seven presses, and reverse wrapping inside the approval dialog. A complete exact reverse list was NOT OBSERVED. |
| Sidebar and navigation | PASS | All role-visible destinations were reachable in the sidebar and Enter opened Incident Explorer. Activation of each sidebar destination was NOT OBSERVED individually. |
| Buttons and links | PASS on checked controls | Refresh, the reported Overview links, Incident Explorer, and approval and rejection buttons. |
| Form fields | PASS | Tab reached Fault report with a visible ring and caret. Other form controls were not individually enumerated. |
| Incident selection | PASS | Tab to P-102 and Enter opened its mechanical vibration detail. |
| Approval action | PASS | Enter activated both the page and confirmation buttons. Owner saw the approval notice. |
| Rejection action | PASS | Enter activated both the page and confirmation buttons. Owner saw the rejection notice. |
| Modal navigation | PASS | Cancel received initial focus and the approval dialog wrapped in both directions. The rejection dialog moved from Cancel to Reject. |
| Escape | PASS | Escape closed the approval dialog without submitting the decision. |
| Focus restoration on Escape | PASS | Focus returned to the page Approve trigger. |
| Focus restoration after successful decision | FAIL | No visible focus reported after either confirmation. After rejection the next Tab reached browser Tab Search. |
| No keyboard trap | PASS on checked paths | Escape left the dialog, and Tab returned from browser controls to Skip to content after rejection. Unvisited content sequences remain NOT OBSERVED. |
| Visible focus indicators | PASS on confirmed controls | Refresh, Evaluation Dashboard (retained), Administration, Skip to content and Fault report. The skip landing and post-confirmation gaps are listed separately. Rings on the other individual controls were NOT OBSERVED. |
| Narrator | NOT OBSERVED | Separate from keyboard and visible focus. |

P18L659 remains **Partial**. No requirement or count changes. The register remains at 203 Verified, 28 Partial, 3 Missing and 4 Not evaluable, with 35 closure-plan entries. The next accessibility step is to verify and correct focus at the skip-link destination and after a decision removes its trigger, then repeat those keyboard checks and record the remaining route content order. Narrator remains a separate evidence gap. SAFE TO CLEAR: No.

Cleanup stopped the eight recorded processes, dropped this run's disposable database and removed its named Compose container, volume and network. The checked demo ports were clear.
