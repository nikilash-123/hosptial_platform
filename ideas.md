# MediPulse AI — Design Direction

## Three stylistic approaches

### Theme Name: Clinical Signal Atlas
Very Brief Intro: A calm, editorial command center that turns operational noise into a legible clinical signal. Warm paper tones, precise data typography, and restrained alert colors make the system feel trustworthy rather than theatrical.
Probability: 0.06

### Theme Name: Night Shift Console
Very Brief Intro: A dark, high-contrast operations console for biomedical teams working under pressure. Saturated status colors and luminous data traces create urgency and focus without turning the product into a gaming interface.
Probability: 0.03

### Theme Name: Care Circuit
Very Brief Intro: A bright, modern health-tech workspace with soft surfaces, optimistic blue-green accents, and modular cards. It emphasizes collaboration and human oversight through approachable visual cues.
Probability: 0.08

## Selected approach: Clinical Signal Atlas

### Design Movement
Contemporary editorial Swiss information design blended with healthcare wayfinding and instrument-panel clarity.

### Core Principles
1. **Signal before decoration.** Every visual treatment must help a biomedical engineer find urgency, evidence, or next action faster.
2. **Calm precision.** The interface should feel composed during a high-pressure shift: generous whitespace, crisp alignment, and only a few purposeful alert colors.
3. **Evidence stays visible.** Scores never appear without their contributing factors, confidence, data freshness, and human review state.
4. **Human authority.** The system recommends; people decide. Review actions are prominent, reversible, and clearly labeled.

### Color Philosophy
The base is a warm mineral canvas rather than a clinical white, reducing glare and giving the dashboard an editorial feel. Deep ink navy provides high-contrast structure. The signature color is **Signal Coral**—a controlled, human-alert red-orange used for critical impact and escalation. Teal indicates verified freshness and operational stability, while amber is reserved for stale or uncertain data. Color is never the only carrier of meaning; every status pairs with text and iconography.

### Layout Paradigm
A persistent left rail anchors navigation while the main workspace uses an asymmetric split: a broad ranked-priority table on the left and a narrower evidence / system-health column on the right. The selected equipment opens as a focused evidence drawer rather than sending the user to a dead-end page. The dashboard begins with a compact briefing band, then lets the ranked queue occupy the visual center.

### Signature Elements
1. A thin coral “signal rule” that marks the selected priority and critical states.
2. Editorial eyebrow labels in uppercase tracking with small monospaced timestamps.
3. Circular impact dials and quiet horizontal factor bars that reveal how a score is formed.

### Interaction Philosophy
Interactions should feel like operating a dependable instrument: direct, reversible, and legible. Selecting a row updates the evidence panel; approving, overriding, or escalating produces an immediate status change and an audit note. Unknown or stale data opens a review cue instead of silently filling gaps.

### Animation
Use short 160–220ms ease-out transitions for selection, hover, and status changes. On first load, metrics and table rows enter with a restrained 40ms stagger, suggesting a live system coming into focus. Score bars may animate once on mount, but never loop. Drawer transitions should use opacity and translate only. Respect reduced-motion preferences.

### Typography System
Use **DM Sans** for interface copy and **IBM Plex Mono** for equipment IDs, timestamps, numeric scores, and data provenance. Headlines are 30–38px with tight tracking and 650 weight. Section labels are 11px uppercase with 0.12em tracking. Body copy is 13–15px with 1.5 line height. Numbers should feel tabular and operational, not decorative.

### Brand Essence
MediPulse AI is the clinical operations signal layer for biomedical engineering teams, helping them repair the equipment that can prevent the most disruption—not simply the equipment that has been down the longest. Personality: **clear, vigilant, humane**.

### Brand Voice
Headlines are decisive but never alarmist. CTAs describe the human action, not an abstract system action. Microcopy names uncertainty plainly.

Example lines:

> “Repair the risk, not just the clock.”

> “Seven procedures are exposed. One alternative is verified.”

### Wordmark & Logo
The mark is a compact pulse-and-cross symbol: a single coral diagnostic line that rises through a small navy medical cross, suggesting clinical care meeting operational intelligence. The wordmark uses a custom-tightened lowercase “medipulse” treatment with a slightly offset coral dot on the “i”; it should feel like a product label, not a generic hospital logo.

### Signature Brand Color
**Signal Coral — #E45D4F.** It is warm enough to feel human and distinct enough to reserve for the moments that require attention, review, or escalation.

## Implementation notes

The prototype will use synthetic data only and will not imply live clinical integration. The primary workflow will include a ranked equipment queue, a selected-equipment evidence panel, score factors, freshness / confidence signals, and human-in-the-loop actions. Navigation items that are not implemented will show a clear “Coming soon” toast rather than becoming dead links.
