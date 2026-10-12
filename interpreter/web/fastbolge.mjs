// Thin wrapper around fastbolge.wasm. Works in browsers, workers and Node.
export const HALTED = 0, PAUSED = 1, NO_PROGRAM = 2, UNDEFINED = 3;

export class Fastbolge {
  constructor(exports) {
    this.x = exports;
  }

  static async instantiate(source) {
    const { instance } = await WebAssembly.instantiate(source, {});
    return new Fastbolge(instance.exports);
  }

  #write(bytes) {
    const ptr = this.x.fb_alloc(bytes.length);
    new Uint8Array(this.x.memory.buffer, ptr, bytes.length).set(bytes);
    return ptr;
  }

  #read(ptr, len) {
    return new Uint8Array(this.x.memory.buffer, ptr, len).slice();
  }

  /** mode: "classic" or "fast20". Returns null or a load error message. */
  load(mode, program) {
    const ptr = this.#write(program);
    const r = this.x.fb_load(mode === "fast20" ? 1 : 0, ptr, program.length);
    this.x.fb_free(ptr, program.length);
    return r === 0 ? null : this.message();
  }

  setInput(bytes) {
    const ptr = this.#write(bytes);
    this.x.fb_set_input(ptr, bytes.length);
    this.x.fb_free(ptr, bytes.length);
  }

  /** Run until maxSteps total steps; returns HALTED, PAUSED or UNDEFINED. */
  run(maxSteps) {
    return this.x.fb_run(maxSteps);
  }

  takeOutput() {
    const out = this.#read(this.x.fb_output_ptr(), this.x.fb_output_len());
    this.x.fb_clear_output();
    return out;
  }

  steps() {
    return this.x.fb_steps();
  }

  message() {
    return new TextDecoder().decode(this.#read(this.x.fb_message_ptr(), this.x.fb_message_len()));
  }
}
