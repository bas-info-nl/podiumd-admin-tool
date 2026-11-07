# Common Ground compliance baseline for upstream adoption

Because the Admin Tool is meant to be adopted by Dimpact (ADR 0006), it follows their conventions from day one:

- It is licensed **EUPL-1.2**, includes a `publiccode.yml`, and lives in a public GitHub repository that can later be transferred to Dimpact.
- The UI is built with **NL Design System** components and design tokens, and meets **WCAG 2.2 AA**.
- The UI is in Dutch, with i18n support from the start. Code, comments and documentation are in English.
- The container runs as non-root with a read-only root filesystem. Images are signed and come with an SBOM, and dependencies are scanned in CI.

Adding these afterwards (relicensing, swapping the component library, retrofitting accessibility) would be much more expensive than starting with them.
