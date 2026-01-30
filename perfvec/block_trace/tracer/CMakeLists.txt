cmake_minimum_required(VERSION 3.20)
project(bbtracer LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(LLVM_INSTALL_PREFIX "" CACHE PATH "LLVM install prefix")
if(LLVM_INSTALL_PREFIX STREQUAL "")
  if(EXISTS "/usr/lib/llvm-22/lib/cmake/llvm/LLVMConfig.cmake")
    set(LLVM_INSTALL_PREFIX "/usr/lib/llvm-22" CACHE PATH "LLVM install prefix" FORCE)
  elseif(DEFINED ENV{LLVM_HOME} AND EXISTS "$ENV{LLVM_HOME}/lib/cmake/llvm/LLVMConfig.cmake")
    set(LLVM_INSTALL_PREFIX "$ENV{LLVM_HOME}" CACHE PATH "LLVM install prefix" FORCE)
  elseif(EXISTS "${CMAKE_SOURCE_DIR}/../llvm-install/lib/cmake/llvm/LLVMConfig.cmake")
    set(LLVM_INSTALL_PREFIX "${CMAKE_SOURCE_DIR}/../llvm-install" CACHE PATH "LLVM install prefix" FORCE)
  else()
    message(FATAL_ERROR "LLVM not found. Set -DLLVM_INSTALL_PREFIX=... (expected <prefix>/lib/cmake/llvm/LLVMConfig.cmake).")
  endif()
endif()
list(APPEND CMAKE_PREFIX_PATH "${LLVM_INSTALL_PREFIX}/lib/cmake/llvm")

find_package(LLVM REQUIRED CONFIG)
message(STATUS "Found LLVM ${LLVM_PACKAGE_VERSION} at ${LLVM_INSTALL_PREFIX}")

separate_arguments(LLVM_DEFINITIONS_LIST NATIVE_COMMAND "${LLVM_DEFINITIONS}")

add_compile_options(${LLVM_DEFINITIONS_LIST})
include_directories(${LLVM_INCLUDE_DIRS})

if(NOT TARGET zstd::libzstd_shared)
  find_library(BBTRACE_ZSTD_LIBRARY
    NAMES zstd libzstd libzstd.so.1
    PATHS /lib/x86_64-linux-gnu /usr/lib/x86_64-linux-gnu
  )
  if(BBTRACE_ZSTD_LIBRARY)
    add_library(zstd::libzstd_shared UNKNOWN IMPORTED)
    set_target_properties(zstd::libzstd_shared PROPERTIES
      IMPORTED_LOCATION "${BBTRACE_ZSTD_LIBRARY}"
    )
  endif()
endif()

if(NOT TARGET CURL::libcurl)
  find_library(BBTRACE_CURL_LIBRARY
    NAMES curl libcurl libcurl.so.4
    PATHS /lib/x86_64-linux-gnu /usr/lib/x86_64-linux-gnu
  )
  if(BBTRACE_CURL_LIBRARY)
    add_library(CURL::libcurl UNKNOWN IMPORTED)
    set_target_properties(CURL::libcurl PROPERTIES
      IMPORTED_LOCATION "${BBTRACE_CURL_LIBRARY}"
    )
  endif()
endif()

add_subdirectory(runtime)
add_subdirectory(passes)
