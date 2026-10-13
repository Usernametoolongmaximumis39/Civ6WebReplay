-- -----------------------------------------------
-- -- AUSTRIA FUNCTION
-- -- Effect: Get Great Musician, Writer, and Artist points when a city-state you're suzerain of gains a tile.
-- -- Author: SeelingCat
-- -----------------------------------------------

-- include("InstanceManager.lua");
-- include("SupportFunctions.lua");

-- -----------------------------------------------
-- -- FUNCTION C15_GetValidTraitPlayersNew
-- -- Credits: Chrisy15
-- -----------------------------------------------

-- function C15_GetValidTraitPlayersNew(sTrait)
--     local tValid = {}
--     for k, v in ipairs(PlayerManager.GetWasEverAliveIDs()) do
--         local leaderType = PlayerConfigurations[v]:GetLeaderTypeName()
--         for trait in GameInfo.LeaderTraits() do
--             if trait.LeaderType == leaderType and trait.TraitType == sTrait then 
--                 tValid[v] = true 
--             end;
--         end
--         if not tValid[v] then
--             local civType = PlayerConfigurations[v]:GetCivilizationTypeName()
--             for trait in GameInfo.CivilizationTraits() do
--                 if trait.CivilizationType == civType and trait.TraitType == sTrait then 
--                     tValid[v] = true 
--                 end;
--             end
--         end
--     end
--     return tValid
-- end

-- local sTrait = "TRAIT_CIVILIZATION_MER_CROWNLANDS"
-- local tTraitPlayers = C15_GetValidTraitPlayersNew(sTrait)

-- -----------------------------------------------
-- -- FUNCTION SC_C15_GetIfCityState
-- -- Based on above function by Chrisy15
-- -----------------------------------------------

-- function SC_C15_GetIfCityState(sSearchParameter)
--     local tValid = {}
--     for k, v in ipairs(PlayerManager.GetWasEverAliveIDs()) do
--         local civType = PlayerConfigurations[v]:GetCivilizationTypeName()
--         for trait in GameInfo.Civilizations() do
--             if trait.CivilizationType == civType and trait.StartingCivilizationLevelType == sSearchParameter then 
--                 tValid[v] = true 
--             end
--         end
--     end
--     return tValid
-- end

-- local sSearchParameter = "CIVILIZATION_LEVEL_CITY_STATE"
-- local tCityStateChecker = SC_C15_GetIfCityState(sSearchParameter)

-- ----------------------------------------------
-- local iMusician = GameInfo.GreatPersonClasses["GREAT_PERSON_CLASS_MUSICIAN"].Index
-- local iArtist = GameInfo.GreatPersonClasses["GREAT_PERSON_CLASS_ARTIST"].Index
-- local iWriter = GameInfo.GreatPersonClasses["GREAT_PERSON_CLASS_WRITER"].Index


-- function SC_Austria_Suzerain_Tile_Expand_Bonus(owner, cityID)
-- 	local pPlayer = Players[owner]
-- 	local pPlayerConfig = PlayerConfigurations[owner]
--     local pPlayerInfluence = pPlayer:GetInfluence()

    
--     local iPointsToGive = 15
    

--     print ("owner", owner)
--     print ("player", pPlayer)

-- 	if tCityStateChecker[owner] and pPlayerInfluence ~= nil then
-- 		local suzerainID = pPlayerInfluence:GetSuzerain()
    
-- 		print ("suzerain",suzerainID)

-- 		if suzerainID ~=-1 and tTraitPlayers[suzerainID] then
-- 			local pSuzerain = Players[suzerainID]
--             print ("Suzerain Found, assigning points")
-- 			pSuzerain:GetGreatPeoplePoints():ChangePointsTotal(iMusician, iPointsToGive)
-- 			pSuzerain:GetGreatPeoplePoints():ChangePointsTotal(iArtist, iPointsToGive)
-- 			pSuzerain:GetGreatPeoplePoints():ChangePointsTotal(iWriter, iPointsToGive)

--             if pSuzerain:IsHuman() then
--                 local pSuzerainCities = pSuzerain:GetCities()
--                 local pCapital = pSuzerainCities:GetCapitalCity()
--                 local iCityXValue = pCapital:GetX()
--                 local iCityYValue = pCapital:GetY()
--                 print (iCityXValue, iCityYValue)
--                 Game.AddWorldViewText(playerID, Locale.Lookup("[COLOR_FLOAT_CULTURE] Earned [ICON_GreatMusician], [ICON_GreatWriter], and [ICON_GreatArtist] points from your city-state's growth![ENDCOLOR]"), iCityXValue, iCityYValue, 0)
--             end
-- 		end
-- 	end
-- end



















-- Events.CityTileOwnershipChanged.Add(SC_Austria_Suzerain_Tile_Expand_Bonus)