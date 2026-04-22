use serde::Serialize;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ShellState {
    mode: &'static str,
    workspace_label: &'static str,
    backend_status: &'static str,
    storage_mode: &'static str,
}

#[tauri::command]
fn get_shell_state() -> ShellState {
    ShellState {
        mode: "Local workspace",
        workspace_label: "MCP_NetLogo",
        backend_status: "Frontend scaffold ready",
        storage_mode: "SQLite + workspace files",
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![get_shell_state])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
