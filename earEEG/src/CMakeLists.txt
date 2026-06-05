# This file was automatically generated for projects
# without default 'CMakeLists.txt' file.

FILE(GLOB_RECURSE app_sources ${CMAKE_SOURCE_DIR}/src/*.*)
list(REMOVE_ITEM app_sources "${CMAKE_SOURCE_DIR}/src/wifi_sta.c")

idf_component_register(SRCS ${app_sources})
