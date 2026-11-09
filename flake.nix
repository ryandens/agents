{
  description = "Development tools for the agents Dagger pipeline";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    dagger.url = "github:dagger/nix";
    dagger.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = {nixpkgs, dagger, ...}: let
    systems = ["x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin"];
    forAllSystems = nixpkgs.lib.genAttrs systems;
    version = nixpkgs.lib.removePrefix "v" (
      nixpkgs.lib.removeSuffix "\n" (builtins.readFile ./.dagger-version)
    );
  in {
    devShells = forAllSystems (system: let
      pkgs = nixpkgs.legacyPackages.${system};
      daggerCli = dagger.packages.${system}.dagger;
    in {
      default = assert nixpkgs.lib.assertMsg (daggerCli.version == version)
        "Dagger's Nix input must match .dagger-version; update flake.lock and the CLI pin together.";
        pkgs.mkShell {
          packages = [daggerCli pkgs.just pkgs.uv pkgs.python3 pkgs.git pkgs.docker-client];
        };
    });
  };
}
