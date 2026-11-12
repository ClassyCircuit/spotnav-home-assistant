// Presentation calculations shared by hosts. No defaults are supplied for data.
export const validSocAssumptions = ({ startingSoc, capacityKwh, efficiency } = {}) =>
  Number.isFinite(startingSoc) && startingSoc >= 0 && startingSoc <= 100 &&
  Number.isFinite(capacityKwh) && capacityKwh > 0 &&
  Number.isFinite(efficiency) && efficiency > 0 && efficiency <= 1;

export function projectSoc(rows, { startingSoc, capacityKwh, efficiency } = {}) {
  let soc = validSocAssumptions({ startingSoc, capacityKwh, efficiency }) ? startingSoc : null;
  return rows.map(row => {
    if (soc == null || !Number.isFinite(row.energy) || row.energy < 0) soc = null;
    else soc = Math.min(100, soc + row.energy * efficiency / capacityKwh * 100);
    return { ...row, projectedSoc: soc };
  });
}

export const total = rows => {
  const energy = rows.length > 0 && rows.every(row => Number.isFinite(row.energy) && row.energy >= 0) ? rows.reduce((s, row) => s + row.energy, 0) : null;
  const cost = rows.length > 0 && rows.every(row => Number.isFinite(row.cost)) ? rows.reduce((s, row) => s + row.cost, 0) : null;
  const validEnergy = Number.isFinite(energy) ? energy : null;
  const validCost = Number.isFinite(cost) ? cost : null;
  const average = validEnergy > 0 && validCost != null ? validCost * 100 / validEnergy : null;
  return { energy: validEnergy, cost: validCost, centsPerKwh: Number.isFinite(average) ? average : null };
};

export const money = value => !Number.isFinite(value) ? 'Unknown' : `${value < 0 ? '−' : ''}€${Math.abs(value).toFixed(2)}`;
