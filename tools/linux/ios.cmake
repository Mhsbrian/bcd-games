# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 B Honey (Mhsbrian/bcd-games)
#
# CMake toolchain file: arm64 iOS from Linux, with the open toolchain's clang and an Xcode's iPhoneOS SDK
# mounted at /opt/darwin (tools/linux/bx). The Linux stand-in for what CMake asks xcrun on a Mac.
set(CMAKE_SYSTEM_NAME iOS)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
set(BCD_DARWIN /opt/darwin CACHE PATH "xtool's Darwin SDK bundle")
set(CMAKE_OSX_SYSROOT "${BCD_DARWIN}/Developer/Platforms/iPhoneOS.platform/Developer/SDKs/iPhoneOS.sdk" CACHE PATH "")
set(CMAKE_OSX_ARCHITECTURES arm64 CACHE STRING "")
if(NOT CMAKE_OSX_DEPLOYMENT_TARGET)
  set(CMAKE_OSX_DEPLOYMENT_TARGET 17.0 CACHE STRING "")
endif()
set(CMAKE_C_COMPILER clang)
set(CMAKE_CXX_COMPILER clang++)
set(CMAKE_ASM_COMPILER clang)
set(CMAKE_OBJC_COMPILER clang)
set(CMAKE_OBJCXX_COMPILER clang++)
foreach(lang C CXX ASM OBJC OBJCXX)
  set(CMAKE_${lang}_COMPILER_TARGET arm64-apple-ios${CMAKE_OSX_DEPLOYMENT_TARGET})
endforeach()
set(CMAKE_AR llvm-ar CACHE FILEPATH "")
set(CMAKE_RANLIB llvm-ranlib CACHE FILEPATH "")
set(CMAKE_NM llvm-nm CACHE FILEPATH "")
set(CMAKE_LINKER "${BCD_DARWIN}/toolset/bin/orig/ld64.lld" CACHE FILEPATH "")
set(CMAKE_INSTALL_NAME_TOOL true CACHE FILEPATH "")   # nothing here installs a dylib
# Only static archives and objects are made here; CMake's compiler check must not try to link a program.
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)
set(CMAKE_FIND_ROOT_PATH "${CMAKE_OSX_SYSROOT}")
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
