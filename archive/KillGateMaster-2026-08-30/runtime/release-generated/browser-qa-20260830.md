# Local browser verification — August 30, 2026

Surface: Codex in-app browser, separate localhost server, synthetic data only.
The server's venture and wallet paths were redirected to a temporary directory.
No customer data, production APIs, credentials, or paid research were used.

- Loaded an idea containing a stored final KILL after RESEARCH_PIVOT. Both the
  visible stage and decision read Kill, with the stop notice present.
- Followed “Complete evidence history and corrections” from the workspace.
- First history page exposed 20 correction controls and an “Older buyer records” link.
- Following that link displayed synthetic buyer 0, the oldest of 21 records, with
  its correction-reason input and “Void mistaken entry” control.
- The same page displayed an ambiguous legacy item under “Legacy evidence requiring
  review,” explained that it was excluded from active evidence, and exposed its
  explicit reason/void action.
- Desktop viewport inspection showed readable headings, table, and correction form.
- At 390 × 844, the page width stayed within the viewport. The table used its own
  horizontal scrollbar (300px visible width, 678px content width), keeping the
  remainder of the page readable without horizontal page overflow.

UI mutation behavior is covered by the application tests. This browser check
covered navigation and visual presentation, not a live provider or billing flow.
The temporary viewport override was reset and the test tab/server were closed afterward.
