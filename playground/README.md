# Playground

Run Malbolge in the browser. `build.py` turns `template.html`, the WebAssembly
build of fastbolge, and the sample programs into one self-contained
`index.html`. It has no server, no build tools and no network requests apart
from web fonts.

```sh
cd ../interpreter
cargo build --release --target wasm32-unknown-unknown --lib
cp target/wasm32-unknown-unknown/release/fastbolge.wasm web/
python3 ../playground/build.py
```

The interpreter runs in a Web Worker in slices of a few million steps, so the
page stays responsive and Stop works at once. Both dialects are supported.
Small fast20 programs run fine, but MalbolgeLisp needs about 3 GB of memory and
does not fit in 32-bit WebAssembly.
