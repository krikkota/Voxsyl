//! Adapted from Handy v0.9.8; Copyright (c) 2025 CJ Pais, MIT.
#![allow(dead_code, unused_imports)]
pub mod audio;
pub mod constants;
pub mod utils;
pub mod vad;
pub use utils::get_cpal_host;
pub use vad::VoiceActivityDetector;
