# UI review - October 15, 2026

The UI now uses shared, labelled sliders for minimum EV, maximum EV and maximum
market width. Maximum sliders end at **No limit**. Their values save with account
settings and presets; moving an EV bound past the other bound adjusts the range
so it remains valid. Existing saved limits above the standard scale are retained.

All six market views and the tracker use collapsible filter panels. On phones
they start collapsed so results appear first. Sportsbook menus support search,
select all, clear all, outside-click dismissal and Escape. Empty EV/props results
offer a reset action. All market views have a short, expandable usage guide.

The shared finish includes readable controls, consistent focus indicators, larger
touch targets, reduced-motion support, tablet card layouts, compact branding,
account navigation and responsive tracker summaries. Calculator and tracker
drawers keep keyboard focus inside while open and restore focus on close.
The refresh action shows a credit-cost review before making a request. Tracker
actions say **Record bet**, distinguishing them from sportsbook placement.

Open-bet badges use yellow for the same player or team in another market and red for the same market. Matching stays within the event and ignores settled bets. Badge text wraps inside its bounds; synthetic player badges were checked at 320, 390, 768 and 1440 pixels without clipping.

## Verified

- Production build and TypeScript validation passed.
- All 140 frontend tests passed, including slider endpoints and saved high limits.
- Eight views checked: EV, props, arbitrage, middles, promo, schedule, tracker and
  account.
- All eight checked at each of these viewport sizes: 320x568, 390x844, 667x375,
  768x1024, 820x1180, 1024x768, 1100x800, 1180x820, 1440x900 and 1920x1080.
- No page-level horizontal overflow or visible error alerts in those 80 checks.
- Visual spot checks included phone cards, expanded filters, desktop tables,
  populated tracker records and a narrow-phone calculator drawer.
- Keyboard maximum-EV adjustment, empty-result recovery and calculator focus
  wrapping were exercised in the browser.

Browser checks used an isolated local fixture API and synthetic account/tracker
data. They made no paid provider requests and placed no wagers. The preview used
separate ports and build output from the operator's running app.

These checks used the in-app Chromium browser. Physical iOS/Android devices and
Safari/Firefox engines were not available for direct testing. This is a UI
verification record, not a claim of production deployment or universal device
certification.

