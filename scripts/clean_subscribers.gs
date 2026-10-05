/**
 * Keeps the subscribers sheet short. Google Apps Script, bound to the spreadsheet
 * that receives the sign-up form's responses.
 *
 * Once a day it deletes:
 *   - every row an address has superseded with a newer answer (only the latest
 *     answer of each address decides its subscription, so older ones are noise);
 *   - the latest answer itself when it is an unsubscription older than
 *     KEEP_UNSUBSCRIBED_DAYS days.
 *
 * Deleting these rows never changes who receives the email.
 *
 * Setup: in the spreadsheet open Extensions > Apps Script, paste this file, save,
 * then run `installTrigger` once and accept the permission prompt.
 */

const KEEP_UNSUBSCRIBED_DAYS = 3;
// Must match UNSUBSCRIBE_WORDS in dolar_market/mailer.py.
const UNSUBSCRIBE_WORDS = ["unsubscribe", "cancel", "baja", "darme de baja", "desuscri", "dejar de"];
const EMAIL_PATTERN = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/;

function addressIn(row) {
  const match = row.join(" ").match(EMAIL_PATTERN);
  return match ? match[0].toLowerCase() : null;
}

function isUnsubscribe(row) {
  return row.some(cell => {
    const text = String(cell).trim().toLowerCase();
    return UNSUBSCRIBE_WORDS.some(word => text.startsWith(word));
  });
}

/** Row numbers (1-based) to delete, given the sheet's values and the current time. */
function rowsToDelete(values, now) {
  const cutoff = now - KEEP_UNSUBSCRIBED_DAYS * 24 * 60 * 60 * 1000;
  const latestRowOf = {};
  values.forEach((row, index) => {
    const address = index > 0 && addressIn(row);
    if (address) latestRowOf[address] = index;
  });
  return values
    .map((row, index) => {
      const address = index > 0 && addressIn(row);
      if (!address) return null; // header and rows without an address are left alone
      const superseded = latestRowOf[address] !== index;
      const submitted = row[0] instanceof Date ? row[0].getTime() : NaN;
      const expired = isUnsubscribe(row) && submitted < cutoff;
      return superseded || expired ? index + 1 : null;
    })
    .filter(rowNumber => rowNumber !== null);
}

function cleanSubscribers() {
  const sheets = SpreadsheetApp.getActiveSpreadsheet().getSheets();
  const sheet = sheets.find(candidate => candidate.getFormUrl()) || sheets[0];
  const doomed = rowsToDelete(sheet.getDataRange().getValues(), Date.now());
  // Bottom-up, so deleting a row does not shift the ones still to delete.
  doomed.reverse().forEach(rowNumber => sheet.deleteRow(rowNumber));
  console.log(`Deleted ${doomed.length} row(s).`);
}

/** Run once: schedules cleanSubscribers every day around 03:00. */
function installTrigger() {
  ScriptApp.getProjectTriggers()
    .filter(trigger => trigger.getHandlerFunction() === "cleanSubscribers")
    .forEach(trigger => ScriptApp.deleteTrigger(trigger));
  ScriptApp.newTrigger("cleanSubscribers").timeBased().everyDays(1).atHour(3).create();
}
