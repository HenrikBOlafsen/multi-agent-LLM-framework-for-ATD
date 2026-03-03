#!/usr/bin/env bash
export DOTNET_WORKDIR="src"
export DOTNET_TEST_TARGET="AngleSharp.Core.sln"

# Two upstream cookie integration tests are environment-dependent (external echo service JSON shape).
# Exclude narrowly; applied identically to baseline/refactor.
export DOTNET_TEST_FILTER="FullyQualifiedName!=AngleSharp.Core.Tests.Library.CookieHandlingTests.SettingCookieIsPreservedViaRedirect&FullyQualifiedName!=AngleSharp.Core.Tests.Library.CookieHandlingTests.SettingThreeCookiesInOneRequestAreTransportedToNextRequest"