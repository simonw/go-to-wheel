package main

import (
	"fmt"
	"os"
	"strings"
)

func main() {
	if len(os.Args) > 1 {
		if os.Args[1] == "--version" {
			fmt.Println("go-example 1.0.0")
			return
		}
		if os.Args[1] == "--help" {
			fmt.Println("Usage: go-example [options] [args...]")
			fmt.Println("")
			fmt.Println("Options:")
			fmt.Println("  --version  Show version")
			fmt.Println("  --help     Show this help")
			fmt.Println("  --echo     Echo the remaining arguments")
			return
		}
		if os.Args[1] == "--echo" {
			fmt.Println(strings.Join(os.Args[2:], " "))
			return
		}
	}
	fmt.Println("Hello from go-example!")
}
