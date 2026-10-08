/**
 * Installs every trigger of the project. Run `installTriggers` once after setting
 * the project up, and again whenever the list below changes; it replaces whatever
 * triggers exist. Times are Bolivia time (the project's time zone) and Google
 * starts a timed trigger within about fifteen minutes of the minute asked for.
 */

function daily(handler, hour) {
  ScriptApp.newTrigger(handler).timeBased().everyDays(1).atHour(hour).nearMinute(0).create();
}

function installTriggers() {
  ScriptApp.getProjectTriggers().forEach(trigger => ScriptApp.deleteTrigger(trigger));
  ScriptApp.newTrigger("cleanSubscribers").forSpreadsheet(SpreadsheetApp.getActiveSpreadsheet()).onFormSubmit().create();
  daily("cleanSubscribers", 3);
  daily("startReading", 7);
  daily("startEmail", 8);
  daily("startReading", 19);
}
