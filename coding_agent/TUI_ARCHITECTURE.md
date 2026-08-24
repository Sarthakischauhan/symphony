# TUI Coding Agent Architecture

## Startup and execution flow

```mermaid
flowchart TD
    A["coding-agent-tui"] --> B["tui.__main__.main()"]

    B --> C{"--resume?"}
    C -- Yes --> D["Load SQLite sessions"]
    D --> E["ResumeApp selects session"]
    E --> F["run_tui(...)"]
    C -- No --> F

    F --> G["load_dotenv()"]
    G --> H["Create CodingAgentApp"]
    H --> I["Textual App.run()"]

    I --> J["CodingAgentApp.on_mount()"]
    J --> K["Create TextualControlPlane"]
    J --> L["build_agent(...)"]

    L --> M["Read environment and explicit --model"]
    M --> M1["OpenAI credentials/config"]
    M --> M2["Anthropic credentials/config"]
    M --> M3["Gemini credentials/config"]

    L --> N["build_default_registry()"]
    N --> N1["Register every credentialed provider"]
    N1 --> N2["Resolve provider:model"]
    N2 --> O["Create CodingAgent"]

    O --> P["Build workspace tools"]
    P --> Q["Wrap tools with approvals"]
    O --> R["Create CoreHarness"]
    O --> S["Configure SQLite persistence"]
    O --> T["Configure optional learning"]

    J --> U["TUI is ready"]
    U --> V["User enters prompt"]

    V --> W{"Slash command?"}
    W -- Yes --> X["CommandManager runs command"]
    W -- No --> Y{"Agent available and not busy?"}

    Y -- No --> Z["Show notice"]
    Y -- Yes --> AA["Disable composer"]
    AA --> AB["Start Textual worker"]

    AB --> AC["@work run_agent()"]
    AC --> AD["_run_agent_turn()"]
    AD --> AE["CodingAgent.run(user_input)"]

    AE --> AF["Prepare system prompt"]
    AF --> AG{"Plan mode?"}
    AG -- Yes --> AH["Restrict tools to read_file/search"]
    AG -- No --> AI["Use normal tools"]

    AH --> AJ["CoreHarness.run()"]
    AI --> AJ

    AJ --> AK["Model/tool execution loop"]
    AK --> AL["Emit control-plane events"]
    AL --> AM["EventPresenter updates transcript"]
    AK --> AN["Persist conversation"]
    AK --> AO["Return HarnessResult"]

    AO --> AP{"Plan mode?"}
    AP -- Yes --> AQ["Save plan"]
    AP -- No --> AR["Schedule learning reflection"]

    AQ --> AS["Re-enable composer"]
    AR --> AS
    AS --> AT["TUI waits for next prompt"]

    V -. "Esc / Ctrl+X" .-> AU["Request cancellation"]
    AU --> AJ
```

## Prompt execution sequence

```mermaid
sequenceDiagram
    participant User
    participant TUI as CodingAgentApp
    participant Agent as CodingAgent
    participant Harness as CoreHarness
    participant Model as Selected Provider Model
    participant Tools as Workspace Tools

    User->>TUI: Submit prompt
    TUI->>TUI: Disable composer and start worker
    TUI->>Agent: run(user_input)
    Agent->>Agent: Prepare prompt and tools
    Agent->>Harness: run(user_input)

    loop Agent turn
        Harness->>Model: Send conversation
        Model-->>Harness: Response or tool call

        alt Tool call
            Harness->>Tools: Execute tool
            Tools-->>Harness: Tool result
            Harness-->>TUI: Control-plane event
            TUI->>TUI: Update transcript
        else Final response
            Model-->>Harness: Final answer
        end
    end

    Harness-->>Agent: HarnessResult
    Agent-->>TUI: Result
    TUI-->>User: Display response
    TUI->>TUI: Re-enable composer
```

## Key execution path

```text
coding-agent-tui
  → main()
  → run_tui()
  → CodingAgentApp.run()
  → on_mount()
  → build_agent()
  → CodingAgent(CoreHarness)
  → user submits prompt
  → Textual worker run_agent()
  → CodingAgent.run()
  → CoreHarness.run()
  → model/tool loop
```

The TUI creates the `CodingAgent` in-process and runs it asynchronously inside Textual's event loop; it does not launch the agent as a separate subprocess.
