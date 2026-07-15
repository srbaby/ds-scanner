export const EXECUTION_PRIORITY = Object.freeze({ SELL: 0, REDUCE: 1, ADD: 2, BUY: 2, HOLD: 3 });

export function normalizeAction(action) {
  const value = String(action || '').trim().toUpperCase();
  return EXECUTION_PRIORITY[value] === undefined ? 'HOLD' : value;
}

export function actionPriority(action) {
  return EXECUTION_PRIORITY[normalizeAction(action)];
}

export function dashboardIsFresh(dashboard, day) {
  return Boolean(dashboard?.generated_at && String(dashboard.generated_at).slice(0, 10) === day);
}

export function sortHoldingsForExecution(holdings, operationForSymbol) {
  return [...holdings].sort((left, right) => {
    const leftPriority = actionPriority(operationForSymbol(left)?.action);
    const rightPriority = actionPriority(operationForSymbol(right)?.action);
    return leftPriority - rightPriority || String(left.symbol).localeCompare(String(right.symbol));
  });
}
