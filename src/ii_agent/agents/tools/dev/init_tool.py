import json
import shlex
from typing import TYPE_CHECKING, Any

from ii_agent.projects.databases.models import DatabaseSource, ProjectDatabase
from ii_agent.projects.databases.repository import ProjectDatabaseRepository
from ii_agent.projects.repository import ProjectRepository
from ii_agent.projects.secrets.service import SecretService
from ii_agent.core.container import get_app_container
from ii_agent.core.db import get_db_session_local
from ii_agent.agents.tools.base import TextContent, ToolResult
from ii_agent.agents.tools.sandbox.base import BaseSandboxTool
from ii_agent.core.logger import logger

if TYPE_CHECKING:
    from ii_agent.agents.agent import IIAgent
    from ii_agent.agents.tools.function import FunctionCall

# Template installation plus a cold Next.js boot can take several minutes in E2B.
DEFAULT_TIMEOUT = 300

# Name
NAME = "fullstack_project_init"
DISPLAY_NAME = "Initialize application template"

# Description
DESCRIPTION = """Initializes a complete fullstack web application from pre-configured templates with modern development tools and best practices.
## Overview
This tool scaffolds production-ready fullstack applications with automated dependency management, testing infrastructure, and deployment configurations. Choose from optimized templates that include modern UI components, authentication, database integration, and comprehensive testing setups.
## Available Frameworks (default: nextjs-shadcn)
### nextjs-shadcn
Modern TypeScript fullstack with premium UI components
- Frontend: Next.js 14+ (App Router), TypeScript, Tailwind CSS, shadcn/ui components
- Build Tools: Bun package manager, Biome linter/formatter, Jest testing
- Features: Server-side rendering, built-in authentication (NextAuth), Prisma ORM, advanced animations (Framer Motion), real-time features (Socket.io)
- Use Case: Enterprise applications, content management systems, e-commerce platforms
### react-shadcn-python
Fullstack JavaScript + Python with FastAPI backend
- Frontend: React + Vite, JavaScript, Tailwind CSS, shadcn/ui components
- Backend: FastAPI, SQLAlchemy, Pydantic, comprehensive testing suite
- Build Tools: Bun (frontend), pip (backend), automated testing with pytest
- Features: REST API, JWT authentication, database migrations, OpenAPI documentation
- Use Case: API-driven applications, data dashboards, microservices architecture
## Development Guidelines
### Backend Standards
- Testing Requirements: Comprehensive test coverage for all endpoints and business logic
  * Unit tests for all functions and classes
  * Integration tests for API endpoints
  * Edge case and error handling coverage
  * All tests must pass before deployment
- API Design: Follow RESTful principles with OpenAPI documentation
- Security: Input validation, authentication, authorization, SQL injection prevention
### Frontend Standards
- UI/UX: Modern, responsive design using Tailwind CSS utility classes
- Component Architecture: Reusable, composable React components
- State Management: Context API or external libraries as needed
- Performance: Code splitting, lazy loading, optimized builds
- Accessibility: WCAG compliance, semantic HTML, proper ARIA labels
### Deployment Configuration
- Default Ports:
  * Backend: `8080` (auto-increment if unavailable)
  * Frontend: `3000` (auto-increment if unavailable)
- Environment: Development, staging, and production configurations
- Monitoring: Error tracking, performance monitoring, logging
### Debugging Best Practices
- API Testing: Test all endpoints with appropriate HTTP clients
- Error Analysis: Monitor console output and application logs
- Documentation: Consult framework documentation and community resources
- Incremental Development: Test components and features iteratively
## Post-Initialization Steps
1. Navigate to project directory: `cd <project_name>`
2. Install dependencies (automatically handled by tool)
3. Start development servers
4. Review generated documentation and project structure
5. Begin feature development following established patterns
## Quality Assurance
- All templates include pre-configured linting and formatting
- Automated testing infrastructure is ready for immediate use
- Security best practices are implemented by default
- Performance optimizations are built into the build process

Use Database flag to enable database integration.

## Database Source Options
- `default`: Uses NeonDB (managed Postgres). A connection string will be automatically provisioned.
- `supabase`: Uses Supabase as the database backend. Requires Supabase to be connected via integrations.
  When supabase is selected, the agent should use the available Supabase Composio tools
  (SUPABASE_CREATE_A_PROJECT, SUPABASE_BETA_RUN_SQL_QUERY, SUPABASE_GET_PROJECT_API_KEYS, etc.)
  to create the project, set up tables, and retrieve API keys after initialization.
"""
# Input schema
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "project_name": {
            "type": "string",
            "description": "A name for your project (lowercase, no spaces, use hyphens - if needed). Example: `my-app`, `todo-app`",
        },
        "framework": {
            "type": "string",
            "description": "The framework to use for the project",
            "enum": ["nextjs-shadcn", "react-shadcn-python"],
        },
        "database": {
            "type": "boolean",
            "description": "(Optional) whether this project requires a database connection. A postgres connection will be given if True",
            "default": False,
        },
        "database_source": {
            "type": "string",
            "description": "(Optional) The database provider to use. 'default' uses NeonDB (managed Postgres). 'supabase' uses Supabase - requires Supabase integration to be connected. Only relevant when database=true.",
            "enum": ["default", "supabase"],
            "default": "default",
        },
    },
    "required": ["project_name", "framework"],
}

SUPABASE_INSTRUCTIONS = (
    "\n\n## Supabase Database Setup Required\n"
    "The user chose Supabase as the database provider. You MUST build the entire website/app using Supabase for ALL database operations, authentication, and backend services.\n\n"
    "### Step 1: Get organization ID\n"
    "Call SUPABASE_LIST_ALL_ORGANIZATIONS to get the list of organizations. Extract the `id` from the organization you want to use.\n"
    "If SUPABASE_LIST_ALL_ORGANIZATIONS is not available, call SUPABASE_LIST_ALL_PROJECTS instead and extract the `organization_id` field from any existing project.\n"
    "If neither returns an organization ID, ask the user to provide their Supabase organization ID from https://supabase.com/dashboard.\n\n"
    "### Step 2: Create Supabase project\n"
    "Call SUPABASE_CREATE_A_PROJECT with ONLY these 4 required parameters:\n"
    '  - name: "<project-name>" (string, required)\n'
    '  - organization_id: "<org-id-from-step-1>" (string, required)\n'
    '  - region: "us-east-1" (string, required)\n'
    '  - db_pass: "<strong-password>" (string, required - generate a strong password with only alphanumeric characters)\n'
    "DO NOT pass any other parameters (no plan, no template_url, no kps_enabled, no postgres_engine, no release_channel, no desired_instance_size). "
    "Passing empty strings for optional URL fields will cause validation errors.\n"
    "IMPORTANT: Save the project 'ref' (project reference ID) from the response - you need it for all subsequent Supabase API calls.\n\n"
    "### Step 3: Get API keys\n"
    "Use SUPABASE_GET_PROJECT_API_KEYS with ref=<project-ref> (required) to retrieve the project API keys (anon key, service role key).\n\n"
    "### Step 4: Configure environment variables\n"
    "Save the Supabase URL and keys as environment variables in .env:\n"
    "   - NEXT_PUBLIC_SUPABASE_URL=https://<project-ref>.supabase.co\n"
    "   - NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon-key>\n"
    "   - SUPABASE_SERVICE_ROLE_KEY=<service-role-key> (for server-side operations)\n\n"
    "### Step 5: Install and set up Supabase client\n"
    "Install @supabase/supabase-js and create a Supabase client utility (e.g. lib/supabase.ts).\n\n"
    "### Step 6: Design and create database schema\n"
    "Use SUPABASE_BETA_RUN_SQL_QUERY with ref=<project-ref> to create all required tables, indexes, and RLS policies. "
    "Design the schema based on the app requirements.\n\n"
    "### Step 7: Build with Supabase throughout\n"
    "Use the Supabase client for ALL data operations: queries, inserts, updates, deletes, real-time subscriptions, and auth. "
    "Do NOT use direct Postgres connections or any other database. Every data interaction must go through Supabase.\n"
)


class FullStackInitTool(BaseSandboxTool):
    name = NAME
    display_name = DISPLAY_NAME
    description = DESCRIPTION
    input_schema = INPUT_SCHEMA
    read_only = False

    async def on_tool_start(self, agent: "IIAgent", fc: "FunctionCall") -> None:
        await super().on_tool_start(agent, fc)
        self._session_id = getattr(agent, "session_id", None)
        self._user_id = getattr(agent, "user_id", None)
        self._host_url = None

        try:
            get_host = getattr(self.sandbox, "get_host", None)
            if callable(get_host):
                self._host_url = await get_host()
            else:
                logger.warning("Host url not supported for this provider")
        except Exception as exc:
            logger.warning("Failed to derive sandbox host_url: {}", exc)
            logger.warning("Failed to derive sandbox host_url: {}", exc)

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        try:
            database_url = None

            if tool_input.get("database"):
                session_id = str(self._session_id) if self._session_id else None
                database_source = tool_input.get("database_source", "default")

                # Supabase database source: skip NeonDB provisioning
                if database_source == "supabase":
                    if not session_id:
                        return ToolResult(
                            llm_content="Cannot initialize database: no session_id available. A session must be created before initializing a project with database.",
                            user_display_content="Cannot initialize database: no session_id available.",
                            is_error=True,
                        )

                    # Record Supabase as the database source (no connection string yet)
                    _db_repo = ProjectDatabaseRepository()
                    async with get_db_session_local() as db:
                        existing_db_record = await _db_repo.get_active_by_session_id(
                            db, session_id=session_id
                        )
                    if not existing_db_record:
                        async with get_db_session_local() as db:
                            await _db_repo.save(
                                db,
                                ProjectDatabase(
                                    session_id=session_id,
                                    source=DatabaseSource.SUPABASE,
                                    connection_string="pending_supabase_setup",
                                    db_metadata={"database_source": "supabase"},
                                ),
                            )

                    # Run init without database_url, append Supabase instructions after
                    result = await self._run_cli(tool_input)

                    # Append Supabase setup instructions
                    if isinstance(result.llm_content, str):
                        result.llm_content += SUPABASE_INSTRUCTIONS
                    elif isinstance(result.llm_content, list):
                        result.llm_content.append(
                            TextContent(type="text", text=SUPABASE_INSTRUCTIONS)
                        )

                    return result

                # Default database source: NeonDB provisioning
                if not session_id:
                    return ToolResult(
                        llm_content="Cannot initialize database: no session_id available. A session must be created before initializing a project with database.",
                        user_display_content="Cannot initialize database: no session_id available.",
                        is_error=True,
                    )

                _db_repo = ProjectDatabaseRepository()
                async with get_db_session_local() as db:
                    existing_db_record = await _db_repo.get_active_by_session_id(
                        db, session_id=session_id
                    )
                if existing_db_record:
                    database_url = existing_db_record.connection_string
                else:
                    from ii_agent.agents.tools.clients import tool_client

                    db_connection = await tool_client.database_connection("postgres", session_id)
                    database_url = db_connection.get("connection_string")

                    async with get_db_session_local() as db:
                        await _db_repo.save(
                            db,
                            ProjectDatabase(
                                session_id=session_id,
                                source=DatabaseSource.NEONDB,
                                connection_string=db_connection.get("connection_string", ""),
                                host=db_connection.get("host"),
                                database_name=db_connection.get("database_name"),
                                role_name=db_connection.get("role_name"),
                                branch_name=db_connection.get("branch_name"),
                                db_metadata={
                                    "project_id": db_connection.get("project_id"),
                                    "project_name": db_connection.get("project_name"),
                                    "is_new_project": db_connection.get("is_new_project"),
                                    "current_project_count": db_connection.get(
                                        "current_project_count"
                                    ),
                                    "databases_in_project": db_connection.get(
                                        "databases_in_project"
                                    ),
                                    "capacity_remaining": db_connection.get("capacity_remaining"),
                                    "original_database_name": db_connection.get(
                                        "original_database_name"
                                    ),
                                    "time_taken_ms": db_connection.get("time_taken_ms"),
                                },
                            ),
                        )

            return await self._run_cli(tool_input, database_url=database_url)
        except Exception as e:
            logger.exception("Failed to initialize project")
            return ToolResult(
                llm_content="Failed to initialize project: " + str(e),
                user_display_content="Failed to initialize project: " + str(e),
                is_error=True,
            )

    async def _run_cli(
        self,
        tool_input: dict[str, Any],
        database_url: str | None = None,
    ) -> ToolResult:
        """Build and execute the ii-app web init CLI command."""
        framework = tool_input.get("framework", "nextjs-shadcn")
        project_name = tool_input["project_name"]

        cmd_parts = [
            "ii-app",
            "web",
            "init",
            framework,
            "--project-name",
            project_name,
            "--workspace",
            "/workspace",
            "--json",
        ]

        if self._host_url:
            cmd_parts.extend(["--host-url", self._host_url])

        if database_url:
            cmd_parts.extend(["--database-url", database_url])

        cmd = " ".join(shlex.quote(p) for p in cmd_parts)
        output = await self.sandbox.run_command(cmd, timeout=DEFAULT_TIMEOUT)
        result = json.loads(output)

        return ToolResult(
            llm_content=[TextContent(type="text", text=output)],
            user_display_content=result,
        )

    async def on_tool_end(self, agent: "IIAgent", fc: "FunctionCall") -> None:
        if fc.error:
            return

        session_id = getattr(agent, "session_id", None)
        user_id = getattr(agent, "user_id", None)
        if not session_id:
            return

        tool_result = fc.result
        if not isinstance(tool_result, ToolResult):
            return
        if tool_result.is_error:
            return

        raw_result = None
        if isinstance(tool_result.user_display_content, dict):
            raw_result = tool_result.user_display_content
        if not isinstance(raw_result, dict):
            return

        project_name = raw_result.get("project_name")
        if not isinstance(project_name, str):
            return

        framework = raw_result.get("framework")
        framework_str = framework if isinstance(framework, str) else None
        project_dir = raw_result.get("directory") or raw_result.get("project_directory")
        project_dir_str = project_dir if isinstance(project_dir, str) else None
        description = raw_result.get("description")
        description_str = description if isinstance(description, str) else None
        database = raw_result.get("database")
        database_payload = database if isinstance(database, dict) else None
        if database_payload is None:
            database_payload = await self._get_active_database_payload(str(session_id))
            if database_payload is not None:
                raw_result["database"] = database_payload

        project_record = await self._persist_project_metadata(
            session_id=str(session_id),
            project_name=project_name,
            framework=framework_str,
            project_path=project_dir_str,
            description=description_str,
            database=None,
        )

        if project_record:
            raw_result["project"] = project_record
            tool_result.user_display_content = raw_result

            # Save DATABASE_URL to project secrets after project is created
            if user_id and database_payload:
                database_url = database_payload.get("connection_string")
                if database_url:
                    await self._save_database_url_to_secrets(
                        session_id=str(session_id),
                        user_id=str(user_id),
                        database_url=database_url,
                    )

    async def _persist_project_metadata(
        self,
        *,
        session_id: str,
        project_name: str,
        framework: str | None,
        project_path: str | None,
        description: str | None,
        database: dict | None,
    ) -> dict | None:
        try:
            import uuid as _uuid

            container = get_app_container()
            async with get_db_session_local() as db:
                project = await container.project_service.create_project(
                    db,
                    session_id=_uuid.UUID(session_id),
                    project_name=project_name,
                    framework=framework,
                    project_path=project_path,
                    description=description,
                    database=database,
                )
                if project:
                    return {"id": str(project.id), "name": project.name}
                return None
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to persist project metadata: {}", exc)
            logger.error("Failed to persist project metadata: {}", exc)
            return None

    async def _save_database_url_to_secrets(
        self,
        *,
        session_id: str,
        user_id: str,
        database_url: str,
    ) -> None:
        """Save DATABASE_URL to project secrets (add or overwrite existing secrets)."""
        try:
            import uuid as _uuid

            container = get_app_container()
            session_uuid = _uuid.UUID(session_id)
            user_uuid = _uuid.UUID(user_id)

            async with get_db_session_local() as db:
                secret_service = SecretService(
                    project_repo=ProjectRepository(),
                    config=container.config,
                )
                await secret_service.add_secrets(
                    db,
                    session_id=session_uuid,
                    user_id=user_uuid,
                    secrets={"DATABASE_URL": database_url},
                )

            logger.info("Saved DATABASE_URL to project secrets for session {}", session_id)
        except Exception as exc:
            logger.error("Failed to save DATABASE_URL to project secrets: {}", exc)
            logger.error("Failed to save DATABASE_URL to project secrets: {}", exc)

    async def _get_active_database_payload(
        self,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Return the active ProjectDatabase payload for the session if it exists."""
        try:
            import uuid as _uuid

            session_uuid = _uuid.UUID(session_id)
            db_repo = ProjectDatabaseRepository()
            async with get_db_session_local() as db:
                db_record = await db_repo.get_active_by_session_id(db, session_uuid)

            if not db_record:
                return None

            payload: dict[str, Any] = {
                "id": str(db_record.id),
                "session_id": str(db_record.session_id),
                "source": str(db_record.source),
                "connection_string": db_record.connection_string,
                "host": db_record.host,
                "database_name": db_record.database_name,
                "role_name": db_record.role_name,
                "branch_name": db_record.branch_name,
                "is_active": db_record.is_active,
            }
            if isinstance(db_record.db_metadata, dict):
                payload.update(db_record.db_metadata)

            return {key: value for key, value in payload.items() if value is not None}
        except Exception as exc:
            logger.warning(
                "Failed to load active database payload for session {}: {}",
                session_id,
                exc,
            )
            return None
