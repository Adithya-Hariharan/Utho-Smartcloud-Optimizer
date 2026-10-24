// Ordered feature checkpoints. `npm run verify` walks them in order and stops at the
// first one that fails, so a later feature is never attempted on a broken base.
//
// Check kinds:
//   typecheck        tsc over the whole app
//   data             validate the API fixtures used by the browser tests
//   unit <files>     vitest
//   e2e <files>      playwright, real Chromium against the dev server
//   build            production build
export default [
  { id: 'CP01', title: 'Fallback API data valid (plan shapes, cost invariants)', checks: [['data']] },
  { id: 'CP02', title: 'App shell, routing, header, nav', checks: [['typecheck'], ['e2e', 'e2e/cp02-shell.spec.ts']] },
  { id: 'CP03', title: 'Cost math + formatting (pure logic)', checks: [['unit', 'src/lib']] },
  { id: 'CP04', title: 'Recommendations table, SummaryBar, accept/reject', checks: [['typecheck'], ['e2e', 'e2e/cp04-recommendations.spec.ts']] },
  { id: 'CP05', title: 'Resource drawer: decision, charts, peak replay, trace', checks: [['e2e', 'e2e/cp05-drawer.spec.ts']] },
  { id: 'CP06', title: 'Rejections ("Checked & kept")', checks: [['e2e', 'e2e/cp06-rejections.spec.ts']] },
  { id: 'CP07', title: 'Overview: KPIs, bill trend, growth waterfall', checks: [['e2e', 'e2e/cp07-overview.spec.ts']] },
  { id: 'CP08', title: 'Utilization: fleet table, heatmap, drill-down', checks: [['e2e', 'e2e/cp08-utilization.spec.ts']] },
  { id: 'CP09', title: 'Alerts', checks: [['e2e', 'e2e/cp09-alerts.spec.ts']] },
  { id: 'CP10', title: 'What-if scheduler', checks: [['e2e', 'e2e/cp10-whatif.spec.ts']] },
  { id: 'CP11', title: 'Data quality', checks: [['e2e', 'e2e/cp11-dataquality.spec.ts']] },
  { id: 'CP12', title: 'Assumptions + engine scorecard', checks: [['e2e', 'e2e/cp12-assumptions.spec.ts']] },
  { id: 'CP13', title: 'Preset switcher (F8 reset) + export', checks: [['e2e', 'e2e/cp13-presets-export.spec.ts']] },
  { id: 'CP14', title: 'Forecast & Green', checks: [['e2e', 'e2e/cp14-forecast.spec.ts']] },
  { id: 'CP15', title: 'Role switch (Engineer / Finance / Leadership)', checks: [['e2e', 'e2e/cp15-roles.spec.ts']] },
  { id: 'CP16', title: 'Production build + full regression', checks: [['typecheck'], ['build'], ['e2e']] },
]
