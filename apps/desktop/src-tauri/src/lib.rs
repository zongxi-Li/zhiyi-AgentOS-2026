#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(desktop)]
fn setup_fullscreen_shortcut(app: &mut tauri::App) -> tauri::Result<()> {
    use std::sync::{Arc, Mutex};

    use tauri::{Manager, WindowEvent};
    use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Shortcut, ShortcutState};

    let fullscreen_shortcut = Shortcut::new(None, Code::F11);
    let key_down = Arc::new(Mutex::new(false));
    let toggle_in_flight = Arc::new(Mutex::new(false));
    let handler_shortcut = fullscreen_shortcut.clone();
    let handler_key_down = Arc::clone(&key_down);
    let handler_toggle_in_flight = Arc::clone(&toggle_in_flight);

    app.handle().plugin(
        tauri_plugin_global_shortcut::Builder::new()
            .with_handler(move |app, shortcut, event| {
                if shortcut != &handler_shortcut {
                    return;
                }

                if event.state() == ShortcutState::Released {
                    if let Ok(mut pressed) = handler_key_down.lock() {
                        *pressed = false;
                    }
                    return;
                }

                let should_toggle = handler_key_down
                    .lock()
                    .map(|mut pressed| {
                        if *pressed {
                            false
                        } else {
                            *pressed = true;
                            true
                        }
                    })
                    .unwrap_or(false);
                if !should_toggle {
                    return;
                }

                let Some(window) = app.get_webview_window("main") else {
                    return;
                };
                if !window.is_focused().unwrap_or(false) {
                    return;
                }

                let can_toggle = handler_toggle_in_flight
                    .lock()
                    .map(|mut in_flight| {
                        if *in_flight {
                            false
                        } else {
                            *in_flight = true;
                            true
                        }
                    })
                    .unwrap_or(false);
                if !can_toggle {
                    return;
                }

                if let Ok(fullscreen) = window.is_fullscreen() {
                    let _ = window.set_fullscreen(!fullscreen);
                }

                if let Ok(mut in_flight) = handler_toggle_in_flight.lock() {
                    *in_flight = false;
                }
            })
            .build(),
    )?;

    if let Some(window) = app.get_webview_window("main") {
        let app_handle = app.handle().clone();
        let registration_shortcut = fullscreen_shortcut.clone();
        let focus_key_down = Arc::clone(&key_down);
        window.on_window_event(move |event| match event {
            WindowEvent::Focused(true) => {
                if let Ok(mut pressed) = focus_key_down.lock() {
                    *pressed = false;
                }
                let _ = app_handle
                    .global_shortcut()
                    .register(registration_shortcut.clone());
            }
            WindowEvent::Focused(false) => {
                if let Ok(mut pressed) = focus_key_down.lock() {
                    *pressed = false;
                }
                let _ = app_handle
                    .global_shortcut()
                    .unregister(registration_shortcut.clone());
            }
            _ => {}
        });

        if window.is_focused().unwrap_or(false) {
            let _ = app.global_shortcut().register(fullscreen_shortcut.clone());
        }
    }

    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            #[cfg(desktop)]
            setup_fullscreen_shortcut(app)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running 知弈 AgentOS desktop shell")
}
