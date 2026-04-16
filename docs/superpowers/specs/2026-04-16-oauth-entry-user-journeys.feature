@auth @oauth @login @openai @ii
Feature: OAuth entry journeys into II-Agent
  In order to enter II-Agent without hidden auth regressions
  As a user in local development or a configured environment
  I want the login experience to behave predictably across OpenAI, II, Google, and local bypass paths

  Background:
    Given the frontend login route loads provider availability from "/auth/providers"
    And the app uses the same ii-agent access token format after every successful login path
    And OpenAI device login can stage a pending Codex connection before app session creation

  @local @bypass @p0
  Scenario: Local development enters the app without II IdP when ENVIRONMENT is local
    Given ENVIRONMENT is "local"
    And II_CLIENT_ID is empty
    And dev auth bypass is enabled automatically
    When the user opens the login page
    Then the "Continue with II" action is visible
    And the "Continue with II" action is enabled
    And the page explains that local dev auth bypass is active
    When the user selects "Continue with II"
    Then the backend creates or resolves a local app user
    And the backend returns the normal ii-agent auth payload
    And the frontend stores the app access token
    And the user lands inside the app

  @local @openai @bypass @p0
  Scenario: Local development stages OpenAI first and then enters the app without II IdP
    Given ENVIRONMENT is "local"
    And II_CLIENT_ID is empty
    And dev auth bypass is enabled automatically
    And the OpenAI device flow completes successfully
    When the login page receives a completed OpenAI staging response
    Then the page shows that OpenAI is staged successfully
    And the "Continue with II" action remains enabled
    When the user selects "Continue with II"
    Then the backend creates or resolves a local app user
    And the backend attaches the staged Codex connection to that user
    And the backend returns the normal ii-agent auth payload
    And the user lands inside the app with Codex configured

  @frontend @resilience @p0
  Scenario: Transient provider lookup failure does not permanently disable login actions
    Given the login page has not yet established provider availability
    And a transient network failure occurs while calling "/auth/providers"
    When the login page renders
    Then it does not permanently mark II login as unavailable
    And it does not permanently mark local bypass as disabled
    When a later "/auth/providers" request succeeds
    Then the login page updates to the latest backend truth
    And the relevant login action becomes enabled without requiring code changes

  @frontend @openai @resilience @p0
  Scenario: OpenAI staging refreshes provider availability before gating the continue action
    Given the login page initially has stale provider availability state
    And the user completes OpenAI device authentication successfully
    When the frontend processes the completed staging response
    Then the frontend re-fetches provider availability
    And the staged OpenAI card uses refreshed availability state
    And the "Continue with II" action is enabled whenever local bypass or II OAuth is available

  @configured @ii @p0
  Scenario: Configured II OAuth uses the real IdP instead of local bypass
    Given II_CLIENT_ID is configured
    And ENVIRONMENT is "local" or "dev"
    When the user selects "Continue with II"
    Then the backend redirects to the II OAuth authorization endpoint
    And the flow uses PKCE and state validation
    And the callback issues the normal ii-agent auth payload

  @configured @ii @openai @p0
  Scenario: Configured II OAuth attaches staged OpenAI during callback
    Given II_CLIENT_ID is configured
    And the user has a valid staged OpenAI pending connection
    When the user completes II OAuth
    Then the II callback resolves the app user
    And the callback attaches the staged Codex connection to that user
    And the callback clears the staged pending connection
    And the frontend receives the normal ii-agent auth payload

  @configured @google @p1
  Scenario: Google sign-in is shown only when the frontend is configured for Google OAuth
    Given VITE_GOOGLE_CLIENT_ID is configured
    When the login page renders
    Then the Google login action is visible
    And the action exchanges the Google auth code for the normal ii-agent auth payload

  @configured @google @p1
  Scenario: Google sign-in is hidden behind clear copy when Google OAuth is not configured
    Given VITE_GOOGLE_CLIENT_ID is empty
    When the login page renders
    Then the Google login action is not interactive
    And the page explains why Google sign-in is unavailable

  @negative @misconfig @p0
  Scenario: Non-local environments do not silently bypass missing II configuration
    Given ENVIRONMENT is "dev" or "staging" or "production"
    And DEV_AUTH_BYPASS_ENABLED is false
    And II_CLIENT_ID is empty
    When the user opens the login page
    Then the II action is visibly unavailable
    And the page explains that II OAuth is not configured
    When the user attempts to call the II login endpoint directly
    Then the backend returns an internal configuration error
    And no app session is created

  @negative @security @p0
  Scenario: OpenAI staging without a pending connection never creates a session side effect
    Given the user completes no OpenAI stage
    When the backend receives a login request without a valid pending connection
    Then the backend creates no Codex configuration from staging
    And the login flow still behaves correctly for the selected auth path

  @negative @security @p0
  Scenario: Expired or tampered staged OpenAI connections are rejected safely
    Given the user has an expired or invalid staged OpenAI pending connection id
    When the login path attempts to consume that pending connection
    Then the backend ignores or clears the invalid pending connection
    And the backend does not attach Codex credentials
    And the user still receives a correct app login result for the underlying auth path

  @negative @security @p0
  Scenario: Invalid II callback state is rejected
    Given II OAuth is configured
    And the callback request contains a missing, mismatched, or tampered state value
    When the backend handles the callback
    Then the backend rejects the request
    And no app session is created
    And no staged OpenAI connection is attached

  @ux @p1
  Scenario: The login route never strands the user without a usable next step
    Given the login page loads in any supported configuration
    When the page finishes rendering
    Then at least one primary entry path is either enabled or clearly explained
    And the copy matches the true backend configuration
    And the UI does not claim a path is unavailable when the backend says it is available
