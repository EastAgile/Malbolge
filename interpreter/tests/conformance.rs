//! Runs every defined case in conformance/cases.json through the library.
use fastbolge::{classic, fast20, mem, BufIo, Exit, Options};
use std::fs;
use std::path::Path;

/// The manifest is written one key per line by gen.py, so a line scanner
/// is enough and keeps the crate free of dependencies.
fn cases() -> Vec<Vec<(String, String)>> {
    let text =
        fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join("../conformance/cases.json"))
            .unwrap();
    let mut out = Vec::new();
    let mut cur = Vec::new();
    for line in text.lines().map(str::trim) {
        if line.starts_with('}') {
            out.push(std::mem::take(&mut cur));
        } else if let Some((k, v)) = line.split_once("\": ") {
            let v = v.trim_end_matches(',').trim_matches('"').to_string();
            cur.push((k.trim_start_matches('"').to_string(), v));
        }
    }
    out
}

#[test]
fn conformance_cases() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../conformance");
    let mut ran = 0;
    for case in cases() {
        let get = |k: &str| case.iter().find(|(a, _)| a == k).map(|(_, v)| v.clone());
        let (name, mode, expect) = (
            get("name").unwrap(),
            get("mode").unwrap(),
            get("expect").unwrap(),
        );
        if expect == "undefined" {
            continue;
        }
        let src = fs::read(root.join(get("program").unwrap())).unwrap();
        let input = get("input")
            .map(|p| fs::read(root.join(p)).unwrap())
            .unwrap_or_default();
        let want = get("output")
            .map(|p| fs::read(root.join(p)).unwrap())
            .unwrap_or_default();
        let prefix: Option<usize> = get("prefix").map(|p| p.parse().unwrap());
        let max_steps = if expect == "runs" {
            20_000_000
        } else {
            2_000_000_000
        };
        let opts = Options {
            max_steps,
            strict: false,
        };
        let mut io = BufIo::new(&input);
        let exit = if mode == "classic" {
            classic::run(&src, &mut io, &opts).exit
        } else {
            match fast20::load::<mem::NativeSpace>(&src) {
                Ok(mut m) => m.run(&mut io, &opts).exit,
                Err(e) => e,
            }
        };
        match expect.as_str() {
            "halt" => {
                assert_eq!(exit, Exit::Halted, "{name}");
                assert!(io.output == want, "{name}: output differs");
            }
            "runs" => {
                let n = prefix.unwrap();
                assert!(
                    io.output.len() >= n && io.output[..n] == want[..],
                    "{name}: first {n} bytes differ"
                );
            }
            "load_error" => assert!(matches!(exit, Exit::LoadError(_)), "{name}: {exit:?}"),
            e => panic!("{name}: unknown expectation {e}"),
        }
        ran += 1;
    }
    assert_eq!(ran, 37);
}
