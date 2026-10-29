// A separate development executable lets the existing desktop remain running.
// All application logic, plugins and security configuration use the same library.
fn main() {
    kinlin_desktop_lib::run()
}
