/**
 * A clock for the GitHub workflows. GitHub's own scheduler delivers scheduled runs
 * hours late, so time-based triggers here start the workflows through GitHub's API,
 * where a started run begins at once. Google Apps Script, in the same project as
 * clean_subscribers.gs.
 *
 * Nothing else moves here: the readings, the dashboard and the email are still
 * produced by the workflows. Starting one twice is harmless: a reading is skipped
 * while a recent one exists and the email goes out once a day.
 *
 * Setup: create a fine-grained GitHub token limited to the repository with the
 * permission "Actions: read and write", save it as the script property
 * GITHUB_TOKEN (Project Settings > Script properties), then run `installTriggers`
 * (triggers.gs). A failed start raises an error, which Google reports by email.
 */

const REPOSITORY = "Mrdavid656/dolar_tracking";
const BRANCH = "main";
// A reading newer than this many minutes means another scheduler already took it.
const SKIP_READING_IF_NEWER_THAN = "120";

/** The URL and options of the request that starts a workflow. */
function dispatchRequest(workflow, inputs, token) {
  return {
    url: `https://api.github.com/repos/${REPOSITORY}/actions/workflows/${workflow}/dispatches`,
    options: {
      method: "post",
      contentType: "application/json",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      payload: JSON.stringify({ ref: BRANCH, inputs: inputs }),
      muteHttpExceptions: true,
    },
  };
}

function startWorkflow(workflow, inputs) {
  const token = PropertiesService.getScriptProperties().getProperty("GITHUB_TOKEN");
  if (!token) throw new Error("The script property GITHUB_TOKEN is not set.");
  const request = dispatchRequest(workflow, inputs, token);
  const response = UrlFetchApp.fetch(request.url, request.options);
  if (response.getResponseCode() !== 204) {
    throw new Error(`GitHub answered ${response.getResponseCode()} for ${workflow}: ${response.getContentText()}`);
  }
  console.log(`Started ${workflow}.`);
}

function startReading() {
  startWorkflow("rates.yml", { if_older_than: SKIP_READING_IF_NEWER_THAN });
}

function startEmail() {
  startWorkflow("email.yml", {});
}
