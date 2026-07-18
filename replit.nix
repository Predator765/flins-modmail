{pkgs}: {
  deps = [
    pkgs.libffi
    pkgs.gdk-pixbuf
    pkgs.pango
    pkgs.gobject-introspection
    pkgs.cairo
  ];
}
