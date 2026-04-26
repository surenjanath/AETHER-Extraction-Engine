---
name: Nocturne Studio
colors:
  surface: '#131313'
  surface-dim: '#131313'
  surface-bright: '#393939'
  surface-container-lowest: '#0e0e0e'
  surface-container-low: '#1c1b1b'
  surface-container: '#201f1f'
  surface-container-high: '#2a2a2a'
  surface-container-highest: '#353534'
  on-surface: '#e5e2e1'
  on-surface-variant: '#c4c7c8'
  inverse-surface: '#e5e2e1'
  inverse-on-surface: '#313030'
  outline: '#8e9192'
  outline-variant: '#444748'
  surface-tint: '#c6c6c7'
  primary: '#ffffff'
  on-primary: '#2f3131'
  primary-container: '#e2e2e2'
  on-primary-container: '#636565'
  inverse-primary: '#5d5f5f'
  secondary: '#c6c6cf'
  on-secondary: '#2f3037'
  secondary-container: '#45464e'
  on-secondary-container: '#b4b4bd'
  tertiary: '#ffffff'
  on-tertiary: '#2f3131'
  tertiary-container: '#e2e2e2'
  on-tertiary-container: '#636565'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#e2e2e2'
  primary-fixed-dim: '#c6c6c7'
  on-primary-fixed: '#1a1c1c'
  on-primary-fixed-variant: '#454747'
  secondary-fixed: '#e2e1eb'
  secondary-fixed-dim: '#c6c6cf'
  on-secondary-fixed: '#1a1b22'
  on-secondary-fixed-variant: '#45464e'
  tertiary-fixed: '#e2e2e2'
  tertiary-fixed-dim: '#c6c6c7'
  on-tertiary-fixed: '#1a1c1c'
  on-tertiary-fixed-variant: '#454747'
  background: '#131313'
  on-background: '#e5e2e1'
  surface-variant: '#353534'
typography:
  headline-lg:
    fontFamily: Noto Serif
    fontSize: 36px
    fontWeight: '500'
    lineHeight: '1.2'
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Noto Serif
    fontSize: 24px
    fontWeight: '500'
    lineHeight: '1.3'
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.6'
    letterSpacing: '0'
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.5'
  label-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: '1'
    letterSpacing: 0.02em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  base: 4px
  xs: 8px
  sm: 16px
  md: 24px
  lg: 40px
  xl: 64px
  sidebar-width: 260px
  inspector-width: 320px
---

## Brand & Style

This design system is built for creative professionals and intellectual environments that require a focused, distraction-free interface. The brand personality is sophisticated, editorial, and calm, evoking the feeling of a premium physical workspace or a high-end literary journal.

The visual style is a blend of **Minimalism** and **Modern Professionalism**. It utilizes high-contrast typography against a near-black canvas to create a clear visual hierarchy without the need for excessive color. The emotional response should be one of quiet confidence and authority, prioritizing content clarity through thoughtful spacing and elegant serif accents.

## Colors

The palette is strictly monochromatic to maintain a professional and focused atmosphere. 

- **Backgrounds:** A deep charcoal-black (`#0D0D0D`) serves as the foundation to minimize eye strain and maximize the depth of the interface.
- **Surfaces:** Subtle shifts to slightly lighter tones (`#1A1A1A`) define interactive containers and cards.
- **Borders:** Extremely thin, low-contrast lines (`#262626`) are used to partition space without creating visual noise.
- **Text:** Pure white (`#FFFFFF`) is reserved for primary headings and active states, while a scale of grays (`#A1A1AA`) is used for secondary information and metadata to manage cognitive load.

## Typography

This design system uses a pairing of a timeless serif for editorial flair and a utilitarian sans-serif for functional clarity.

- **Headlines:** Use **Noto Serif** for main page titles and section headers. This introduces a "studio" aesthetic that feels curated and high-end.
- **Body & UI:** Use **Inter** for all functional text, navigation, and long-form content. Its neutral character ensures that the interface remains secondary to the user's work.
- **Contrast:** Maintain a strict hierarchy by varying font weights and gray-scale values rather than using color.

## Layout & Spacing

The layout follows a structured, multi-pane architecture suitable for complex workflows. It utilizes a three-column model:
1.  **Global Navigation:** A fixed left sidebar with a narrow profile for primary navigation.
2.  **Primary Content:** A wide, fluid center area that holds the main task or editor.
3.  **Contextual Inspector:** A fixed right sidebar for secondary metadata, instructions, or file management.

The spacing rhythm is generous, using a 4px baseline. Large internal margins within cards and containers ensure that text never feels cramped, reinforcing the sophisticated, editorial feel.

## Elevation & Depth

This design system avoids traditional shadows in favor of **Tonal Layering** and **Low-Contrast Outlines**.

- **Level 0 (Background):** The base layer (`#0D0D0D`).
- **Level 1 (Containers):** Cards and sidebars are defined by a slightly lighter fill (`#1A1A1A`) and a 1px solid border (`#262626`).
- **Interaction:** Hover states should be indicated by a subtle increase in border brightness or a very slight tonal shift in the background, rather than an "upward" shadow movement. This keeps the interface feeling flat, modern, and grounded.

## Shapes

The shape language is disciplined and professional. 

- **Primary Radius:** A soft 4px (`0.25rem`) radius is applied to most UI components like buttons, input fields, and small cards. 
- **Large Elements:** Larger containers or main layout sections may use up to 8px (`0.5rem`) for a slightly softer feel, but never exceeding this to avoid looking too "consumer-grade" or playful. 
- **Consistency:** Maintain sharp internal corners within nested elements to preserve the architectural precision of the design.

## Components

### Buttons
Primary buttons use a subtle border and ghost-style background to stay integrated with the dark theme. Secondary buttons are text-only with icons. The "Upload" or "Action" buttons use a dashed border for a tactile, utility feel.

### Cards & Containers
Cards are used to group metadata (e.g., "Memory" or "Files"). They feature a 1px border and a background that is one step lighter than the main workspace. Headings inside cards should use the Serif typeface at a small scale.

### Input Fields
Inputs are dark, using the same background as cards. They should have a subtle border that glows slightly (low-opacity white) when focused. Placeholders are rendered in a medium gray.

### Side Navigation
Active states in the navigation are indicated by a subtle background highlight and a brighter text color. Icons should be thin-stroke (linear) and monochromatic.

### Lists
List items in the main content area use generous vertical padding and subtle horizontal dividers to separate entries, with metadata (timestamps, status) aligned to the right in a smaller, muted font.