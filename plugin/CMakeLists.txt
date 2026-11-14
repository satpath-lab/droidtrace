cmake_minimum_required(VERSION 3.16)
project(droidtrace_plugin C)
set(CMAKE_C_STANDARD 11)
set(QEMU_SRC "" CACHE PATH "Path to QEMU source tree (>= 9.0) providing include/qemu/qemu-plugin.h")
find_path(QEMU_PLUGIN_INCLUDE qemu-plugin.h
  HINTS ${QEMU_SRC}/include/qemu /usr/include/qemu /usr/local/include/qemu REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(GLIB REQUIRED IMPORTED_TARGET glib-2.0)

add_library(insntrace MODULE src/insntrace.c src/ranges.c)
target_include_directories(insntrace PRIVATE include ${QEMU_PLUGIN_INCLUDE})
target_link_libraries(insntrace PRIVATE PkgConfig::GLIB pthread)
target_compile_options(insntrace PRIVATE -Wall -Wextra -Werror=implicit-function-declaration -fvisibility=hidden)
install(TARGETS insntrace LIBRARY DESTINATION lib/droidtrace)
