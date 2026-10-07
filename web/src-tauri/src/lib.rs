//! The native half of the desktop app.
//!
//! The page (web/src) is the same one that runs in the browser. This side adds
//! what a page in a browser is not allowed to do: here, asking the graphics
//! driver how busy the card that runs the model is.

use serde::Serialize;
use std::process::Command;

/// The state of a graphics card, as the page shows it.
#[derive(Debug, PartialEq, Serialize)]
pub struct Gpu {
    name: String,
    memory_used_mb: u32,
    memory_total_mb: u32,
    utilization_percent: u32,
}

const QUERY: &str = "--query-gpu=name,memory.used,memory.total,utilization.gpu";

/// Reads one line of `nvidia-smi --query-gpu=... --format=csv,noheader,nounits`,
/// for example `NVIDIA GeForce RTX 3050 Ti Laptop GPU, 3025, 4096, 37`.
fn parse_gpu(line: &str) -> Option<Gpu> {
    let mut fields = line.split(',').map(str::trim);
    let gpu = Gpu {
        name: fields.next().filter(|name| !name.is_empty())?.to_string(),
        memory_used_mb: fields.next()?.parse().ok()?,
        memory_total_mb: fields.next()?.parse().ok()?,
        utilization_percent: fields.next()?.parse().ok()?,
    };
    Some(gpu)
}

/// The state of the first NVIDIA card, or nothing when there is no card or no driver.
///
/// A command is a function the page can call by name. `async` here means "not on
/// the thread that draws the window", so the window stays responsive while the
/// driver answers.
#[tauri::command(async)]
fn gpu_status() -> Option<Gpu> {
    let mut command = Command::new("nvidia-smi");
    command.args([QUERY, "--format=csv,noheader,nounits"]);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // CREATE_NO_WINDOW: without it a console window flashes behind the app at every call
        command.creation_flags(0x0800_0000);
    }
    let output = command.output().ok()?;
    if !output.status.success() {
        return None;
    }
    parse_gpu(String::from_utf8_lossy(&output.stdout).lines().next()?)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![gpu_status])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_a_line_of_nvidia_smi() {
        let gpu = parse_gpu("NVIDIA GeForce RTX 3050 Ti Laptop GPU, 3025, 4096, 37");
        assert_eq!(
            gpu,
            Some(Gpu {
                name: "NVIDIA GeForce RTX 3050 Ti Laptop GPU".to_string(),
                memory_used_mb: 3025,
                memory_total_mb: 4096,
                utilization_percent: 37,
            })
        );
    }

    #[test]
    fn a_value_the_driver_cannot_report_gives_nothing() {
        // some cards answer [N/A] instead of a number
        assert_eq!(parse_gpu("Some Card, 100, 4096, [N/A]"), None);
    }

    #[test]
    fn text_that_is_not_a_reading_gives_nothing() {
        assert_eq!(parse_gpu(""), None);
        assert_eq!(parse_gpu("NVIDIA-SMI has failed"), None);
    }
}
