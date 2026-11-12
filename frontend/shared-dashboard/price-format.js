// Backend prices/caps are major currency units per kWh. The sample is already
// in euro cents; only the live adapter crosses this display boundary.
export const priceUnit = currency => currency === 'EUR' ? 'c/kWh' : /^[A-Z]{3}$/.test(currency || '') ? `${currency}/kWh` : 'currency unknown/kWh';
export const displayPrice = (price, currency) => Number.isFinite(price) ? (currency === 'EUR' ? price * 100 : price) : null;
export const priceText = value => {
  if (!Number.isFinite(value)) return 'Unknown';
  if (value !== 0 && Math.abs(value) < 0.0001) return value.toExponential(3);
  return new Intl.NumberFormat('en', {maximumFractionDigits: 4, useGrouping: false}).format(Object.is(value, -0) ? 0 : value);
};
// Do not round a saved cap merely by opening or saving another field.
export const capInput = (price, currency) => Number.isFinite(price) ? String(Number(displayPrice(price,currency).toPrecision(15))) : '';
export const capForSave = (text, currency, saved) => {
  if (text === capInput(saved,currency)) return saved == null ? '' : String(saved);
  const normalized=text.trim().replace(',', '.');
  if (currency !== 'EUR' || !normalized || !Number.isFinite(Number(normalized))) return text;
  return String(Number(normalized) / 100);
};
