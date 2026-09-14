/**
 * The currencies an expense or a budget can be denominated in.
 *
 * Must stay in step with `SUPPORTED_CURRENCIES` in `backend/expenses/domain.py`,
 * which rejects anything else with a 400 — a code offered here but refused there
 * is a save that fails for no reason the form can explain.
 *
 * Lives in `lib/` rather than inside the expenses component because the budget
 * needs the same list, and a list of data is not a component's to own.
 */
export const CURRENCIES = [
  'AED', 'ARS', 'AUD', 'BRL', 'CAD', 'CHF', 'CLP', 'CNY', 'COP',
  'CZK', 'DKK', 'EGP', 'EUR', 'GBP', 'HKD', 'HUF', 'IDR', 'ILS',
  'INR', 'ISK', 'JPY', 'KRW', 'MAD', 'MXN', 'MYR', 'NOK', 'NZD',
  'PEN', 'PHP', 'PLN', 'QAR', 'RON', 'SAR', 'SEK', 'SGD', 'THB',
  'TRY', 'TWD', 'UAH', 'USD', 'ZAR',
];
